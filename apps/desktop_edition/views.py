"""
What the offline computer app asks the website (all under /desktop-app/).

    POST activate/         a code typed in once: the computer's licence, and
                           the keys to its levels' lessons
    POST check/            an activated computer checking in: a fresh licence,
                           or "stopped" if its seat was freed or its code ended
    GET  content/latest/   the newest release's list, for that licence's levels
    GET  content/blob/<id>/  one sealed file from it
    GET  public-key/       the key apps check licences with (the app's build
                           reads it, so it never has to be copied by hand)

The app sends its licence in the X-DM-Licence header ("licence.signature").
The app's own build (on GitHub) sends X-DM-Build-Token instead, to download
every level into the installer: DESKTOP_BUILD_TOKEN on the server.
"""

import hmac
import json

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import keys
from .export import blob_path, read_manifest
from .models import Activation, ActivationCode, ContentRelease, clean_code

ATTEMPTS_PER_HOUR = 20


def _json(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _too_many(request):
    key = "desktop-activate-" + (request.META.get("REMOTE_ADDR") or "?")
    count = cache.get(key, 0) + 1
    cache.set(key, count, 60 * 60)
    return count > ATTEMPTS_PER_HOUR


def _why_not(code):
    """Why this code can't be used now, or ""."""
    if not code.is_active:
        return "This code has been stopped. Please contact Diction Masters."
    if code.expired():
        return f"This code ended on {code.valid_until:%d %B %Y}. Please contact Diction Masters to renew it."
    return ""


def licence_for(activation):
    """(licence, signature, keys) for one activated computer."""
    code = activation.code
    levels = code.opens()
    payload = {
        "v": 1,
        "a": activation.pk,
        "code": code.code,
        "holder": code.holder,
        "learner": activation.learner_name,
        "device": activation.device_id,
        "levels": levels,
        "until": code.valid_until.isoformat() if code.valid_until else None,
        "issued": timezone.now().isoformat(),
        "site": settings.SITE_URL,
        "recheck_days": settings.DESKTOP_RECHECK_DAYS,
    }
    body, signature = keys.sign(payload)
    content_keys = {group: keys.content_key_b64(group) for group in [keys.COMMON, *levels]}
    return body, signature, content_keys


def _answer(activation):
    body, signature, content_keys = licence_for(activation)
    latest = ContentRelease.latest()
    return _json({"ok": True, "licence": body, "signature": signature, "keys": content_keys,
                  "release": latest.pk if latest else 0})


@csrf_exempt
@require_POST
def activate(request):
    data = _body(request)
    if _too_many(request):
        return _json({"ok": False, "error": "Too many tries. Wait an hour, then try again."}, 429)
    typed = clean_code(data.get("code"))
    device = str(data.get("device_id") or "").strip()[:80]
    if not typed or not device:
        return _json({"ok": False, "error": "That doesn't look like a Diction Masters code (DM-XXXX-XXXX-XXXX)."}, 400)
    code = ActivationCode.objects.filter(code=typed).first()
    if code is None:
        return _json({"ok": False, "error": "That code wasn't found. Check each letter and try again."}, 404)
    reason = _why_not(code)
    if reason:
        return _json({"ok": False, "error": reason}, 403)
    activation = Activation.objects.filter(code=code, device_id=device).first()
    if activation is None or activation.revoked:
        if code.seats_used() >= code.seats:
            return _json({"ok": False, "error": (
                f"This code is already in use on {code.seats} computer{'s' if code.seats != 1 else ''}, "
                "which is all it allows. Ask Diction Masters to free a seat or add one.")}, 403)
    if activation is None:
        activation = Activation(code=code, device_id=device)
    activation.revoked = False
    activation.device_name = str(data.get("device_name") or "")[:200]
    activation.learner_name = str(data.get("learner_name") or "")[:200]
    activation.system = str(data.get("system") or "")[:40]
    activation.app_version = str(data.get("app_version") or "")[:40]
    activation.last_seen = timezone.now()
    activation.save()
    return _answer(activation)


def _licensed(request):
    """(activation, levels) for the licence a request carries, or None. The
    build token is every level, with no activation."""
    token = request.headers.get("X-DM-Build-Token", "")
    expected = settings.DESKTOP_BUILD_TOKEN
    if token and expected and hmac.compare_digest(token, expected):
        from apps.accounts.access import LEVEL_ORDER

        return None, list(LEVEL_ORDER)
    body, _sep, signature = request.headers.get("X-DM-Licence", "").partition(".")
    payload = keys.verify(body, signature)
    if not payload:
        return None
    activation = Activation.objects.select_related("code").filter(pk=payload.get("a"), device_id=payload.get("device")).first()
    if activation is None or activation.revoked or _why_not(activation.code):
        return None
    return activation, activation.code.opens()


@csrf_exempt
@require_POST
def check(request):
    data = _body(request)
    payload = keys.verify(data.get("licence", ""), data.get("signature", ""))
    if not payload:
        return _json({"ok": False, "stopped": True, "error": "This computer's licence isn't valid. Type your code again."}, 403)
    activation = Activation.objects.select_related("code").filter(pk=payload.get("a"), device_id=payload.get("device")).first()
    if activation is None or activation.revoked:
        return _json({"ok": False, "stopped": True,
                      "error": "This computer has been removed from its code. Type a code to use it again."}, 403)
    reason = _why_not(activation.code)
    if reason:
        return _json({"ok": False, "stopped": True, "error": reason}, 403)
    activation.last_seen = timezone.now()
    activation.app_version = str(data.get("app_version") or activation.app_version)[:40]
    try:
        activation.content_release = int(data.get("release") or 0)
    except (TypeError, ValueError):
        pass
    activation.save(update_fields=["last_seen", "app_version", "content_release"])
    return _answer(activation)


@require_GET
def latest(request):
    found = _licensed(request)
    if found is None:
        return _json({"ok": False, "error": "Not activated."}, 403)
    _activation, levels = found
    release = ContentRelease.latest()
    manifest = read_manifest(release)
    if manifest is None:
        return _json({"ok": True, "release": 0})
    manifest["levels"] = {name: group for name, group in manifest["levels"].items() if name in levels}
    manifest["ok"] = True
    return _json(manifest)


@require_GET
def blob(request, blob_id):
    if _licensed(request) is None:
        return _json({"ok": False, "error": "Not activated."}, 403)
    if not (len(blob_id) == 40 and all(ch in "0123456789abcdef" for ch in blob_id)):
        return _json({"ok": False}, 404)
    name = blob_path(blob_id)
    if not default_storage.exists(name):
        return _json({"ok": False}, 404)
    url = default_storage.url(name)
    if url.startswith(("http://", "https://")):
        return HttpResponseRedirect(url)          # straight from the storage bucket, not through the server
    response = FileResponse(default_storage.open(name, "rb"), content_type="application/octet-stream")
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


@require_GET
def public_key(request):
    return _json({"public_key": keys.public_key_b64()})
