"""
Playing a lesson video, and keeping one for later.

    /videos/play/<ticket>/     the player reads from here
    /videos/keep/<ticket>/     a copy is fetched from here, once allowed
    /videos/prepare/           asks to keep a copy: device, limit, expiry
    /videos/licenses/          what this device may still play, checked
                               whenever it is online
    /videos/devices/           the learner's own devices
    /videos/offline/           the page listing what is kept on this device

Every one of them needs a signed-in account whose access is live, and
the ticket in a link only works for the account it was made for.
"""

import json

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.billing.access import has_access, is_exempt

from . import links, streaming
from .models import OfflineVideoLicense, StudentDevice, device_limit, license_days

MAX_DEVICE_NAME = 80


def _may_watch(user):
    """The same rule as the rest of the learning tools: a running trial,
    a paid plan, or staff."""
    return bool(user.is_authenticated and (is_exempt(user) or has_access(user)))


def _video_for(request, raw, purpose):
    found = links.read_ticket(raw, purpose)
    if not found or found.get("u") != request.user.pk:
        raise Http404("That link has expired. Open the lesson again.")
    video = links.video_from_ticket(found)
    if video is None or not getattr(video, "video_file", None):
        raise Http404("That video has gone.")
    return video


@login_required
@require_GET
def play(request, ticket):
    """The player's own address for a video.

    Django checks who is asking, then hands the player a link straight to
    storage that lasts minutes — so the bytes come from Cloudflare, not
    through this server, and seeking stays quick. Where storage has no
    such links (a local folder in development) the bytes are passed
    through instead."""
    if not _may_watch(request.user):
        raise Http404("That video isn't available on your plan.")
    video = _video_for(request, ticket, links.WATCH)
    short_lived = streaming.brief_link(video.video_file)
    if short_lived:
        response = HttpResponseRedirect(short_lived)
        response["Cache-Control"] = "private, max-age=0, no-store"
        return response
    return streaming.serve(request, video.video_file, content_type=_type_of(video))


@login_required
@require_GET
def keep(request, ticket):
    """The bytes of a copy, for a device that has been allowed one."""
    if not _may_watch(request.user):
        raise Http404("That video isn't available on your plan.")
    video = _video_for(request, ticket, links.KEEP)
    device_id = request.GET.get("device", "")
    licence = _licence_for(request.user, video, device_id)
    if licence is None or not licence.is_live:
        raise Http404("This device isn't allowed to keep that video.")
    return streaming.serve(request, video.video_file, content_type=_type_of(video))


def _type_of(video):
    name = (video.video_file.name or "").lower()
    if name.endswith(".webm"):
        return "video/webm"
    if name.endswith(".ogg") or name.endswith(".ogv"):
        return "video/ogg"
    if name.endswith(".mov"):
        return "video/quicktime"
    return "video/mp4"


def _licence_for(user, video, device_id):
    content_type = ContentType.objects.get_for_model(video)
    return OfflineVideoLicense.objects.filter(
        student=user, content_type=content_type, object_id=video.pk,
        device__device_identifier=device_id,
    ).select_related("device").first()


# ---------------------------------------------------------------------------
# Asking to keep a copy
# ---------------------------------------------------------------------------

@login_required
@require_POST
def prepare(request):
    """May this device keep this video? Registers the device, applies the
    limit, and answers with where to fetch the copy and how long it lasts.

    Nothing secret is sent back: the address is a ticket for this account
    that stops working in a couple of hours, and the copy the browser
    then makes is locked to that browser by a key it keeps to itself.
    """
    if not _may_watch(request.user):
        return JsonResponse({"ok": False, "error": "Your plan doesn't include the lessons just now."}, status=403)

    body = _body(request)
    found = links.read_ticket(body.get("ticket", ""), links.WATCH)
    if not found or found.get("u") != request.user.pk:
        return JsonResponse({"ok": False, "error": "Open the lesson again and try once more."}, status=400)
    video = links.video_from_ticket(found)
    if video is None or not getattr(video, "video_file", None):
        return JsonResponse({"ok": False, "error": "That video has gone."}, status=404)

    device_id = str(body.get("device") or "").strip()[:255]
    if not device_id:
        return JsonResponse({"ok": False, "error": "This browser couldn't be identified."}, status=400)

    device, problem = _device_for(request.user, device_id, str(body.get("device_name") or "")[:MAX_DEVICE_NAME])
    if problem:
        return JsonResponse({"ok": False, "error": problem, "devices": _devices(request.user)}, status=409)

    content_type = ContentType.objects.get_for_model(video)
    title = str(body.get("title") or getattr(video, "video_caption", "") or "Lesson video")[:200]
    try:
        with transaction.atomic():
            licence, _ = OfflineVideoLicense.objects.update_or_create(
                student=request.user, device=device, content_type=content_type, object_id=video.pk,
                defaults={"title": title, "expires_at": OfflineVideoLicense.new_expiry(),
                          "revoked_at": None, "is_active": True},
            )
    except IntegrityError:
        return JsonResponse({"ok": False, "error": "That copy is already being prepared."}, status=409)

    return JsonResponse({
        "ok": True,
        "id": licence.pk,
        "url": links.keep_url(video, request.user) + f"?device={device_id}",
        "size": video.video_file.size,
        "content_type": _type_of(video),
        "expires_at": licence.expires_at.isoformat(),
        "days": license_days(),
        "title": licence.title,
        "watch_url": links.watch_url(video, request.user),
    })


def _device_for(user, device_id, name):
    """This device, registering it if it is new — within the limit."""
    device = StudentDevice.objects.filter(student=user, device_identifier=device_id).first()
    if device is not None:
        if not device.is_active:
            return None, "This device has been turned off for offline copies."
        if name and device.name != name:
            device.name = name
        device.save(update_fields=["name", "last_seen_at"])
        return device, None

    limit = device_limit()
    if StudentDevice.objects.filter(student=user, is_active=True).count() >= limit:
        return None, (f"You can keep lessons on {limit} device{'s' if limit != 1 else ''}. "
                      "Remove one in My devices to use this one.")
    return StudentDevice.objects.create(student=user, device_identifier=device_id, name=name), None


def _body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# What this device may still play, and the devices themselves
# ---------------------------------------------------------------------------

@login_required
@require_POST
def licenses(request):
    """Checked whenever the app is online: which kept copies are still
    good, which have run out, and which have been taken back."""
    device_id = str(_body(request).get("device") or "").strip()[:255]
    rows = (OfflineVideoLicense.objects.filter(student=request.user, device__device_identifier=device_id)
            .select_related("device"))
    renewed = []
    for licence in rows:
        # Still entitled and not revoked: push the date out again, so a
        # learner who keeps using the app never loses a copy mid-week.
        if licence.is_active and licence.revoked_at is None and licence.device.is_active and _may_watch(request.user):
            licence.renew()
        renewed.append({
            "id": licence.pk,
            "video": f"{licence.content_type_id}:{licence.object_id}",
            "title": licence.title,
            "live": licence.is_live,
            "expires_at": licence.expires_at.isoformat(),
        })
    StudentDevice.objects.filter(student=request.user, device_identifier=device_id).update(last_seen_at=timezone.now())
    return JsonResponse({"ok": True, "licenses": renewed, "days": license_days()})


@login_required
@require_POST
def release(request):
    """The learner has removed a copy from this device."""
    body = _body(request)
    licence = OfflineVideoLicense.objects.filter(
        student=request.user, pk=body.get("id"), device__device_identifier=str(body.get("device") or "")).first()
    if licence is not None:
        licence.delete()
    return JsonResponse({"ok": True})


def _devices(user):
    return [
        {"id": device.pk, "name": device.name or "This device", "copies": device.copies_held,
         "last_seen": device.last_seen_at.isoformat(), "active": device.is_active}
        for device in StudentDevice.objects.filter(student=user)
    ]


@login_required
@require_GET
def devices(request):
    return JsonResponse({"ok": True, "devices": _devices(request.user), "limit": device_limit()})


@login_required
@require_POST
def deactivate_device(request, pk):
    """Stop a device keeping copies, and end the ones it holds."""
    device = get_object_or_404(StudentDevice, pk=pk, student=request.user)
    device.is_active = False
    device.save(update_fields=["is_active", "last_seen_at"])
    device.licenses.update(is_active=False, revoked_at=timezone.now())
    return JsonResponse({"ok": True, "devices": _devices(request.user)})


@login_required
def offline_page(request):
    """What this device is holding, and how long each copy has left. The
    list itself is read from the browser's own store, so the page works
    with no connection (static/js/offline_video.js)."""
    return render(request, "videos/offline.html", {
        "days": license_days(),
        "limit": device_limit(),
        "devices": _devices(request.user),
    })
