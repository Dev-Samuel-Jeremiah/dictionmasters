"""The account switcher: several accounts on one device.

A parent with two children and one tablet signs each child in once; after
that, the dashboard's "Switch account" lists them and one tap moves from
one to the other, no password needed. Accounts from the same school are
listed together; accounts from other schools sit behind "Switch school".

How a device remembers an account:
- Signing in (or signing up) on the device remembers the account, unless
  "Remember me on this device" was unticked on the log-in page.
- The device keeps a signed cookie (COOKIE) listing {user id, key}. The
  server keeps only a hash of each key, in DeviceLogin, so a key can't be
  made up, and a copied cookie stops working once the account is removed.
- An account stays on the switcher until someone removes it from the
  device (or its school switches it off). An admin (staff) account, or one
  whose password has changed since, stays listed but asks for its password
  when chosen, so the control room is never one tap away.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core import signing
from django.dispatch import receiver

COOKIE = "dm_accounts"
SALT = "dm.account-switcher"
MAX_ACCOUNTS = 30
AGE = timedelta(days=180)


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def _entries(request):
    """[{"u": user id, "k": key}] from the device's cookie, newest first."""
    raw = request.COOKIES.get(COOKIE)
    if not raw:
        return []
    try:
        data = signing.loads(raw, salt=SALT, max_age=AGE)
    except (signing.BadSignature, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("u"), int) and isinstance(e.get("k"), str)]


def _write(response, entries):
    if entries:
        response.set_cookie(
            COOKIE, signing.dumps(entries[:MAX_ACCOUNTS], salt=SALT, compress=True),
            max_age=int(AGE.total_seconds()), httponly=True, samesite="Lax",
            secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
        )
    else:
        response.delete_cookie(COOKIE, samesite="Lax")


def device_accounts(request):
    """The DeviceLogins remembered on this device, in the device's order,
    each with its .user (and school) and .needs_password: an admin account,
    or one whose password changed since, is listed but asks for it."""
    if hasattr(request, "_dm_device_accounts"):
        return request._dm_device_accounts
    from .models import DeviceLogin

    entries = _entries(request)
    by_hash = {_hash(e["k"]): e["u"] for e in entries}
    rows = {}
    for row in DeviceLogin.objects.filter(key_hash__in=by_hash).select_related("user", "user__school"):
        if by_hash.get(row.key_hash) != row.user_id or not row.user.is_active:
            continue
        current = secrets.compare_digest(row.auth_hash, row.user.get_session_auth_hash())
        row.needs_password = row.user.is_staff or row.user.is_superuser or not current
        row.user.switch_locked = row.needs_password
        rows[row.user_id] = row
    found = [rows[e["u"]] for e in entries if e["u"] in rows]
    request._dm_device_accounts = found
    return found


def remember(request, response, user):
    """Put this account on the device's switcher (or refresh its key)."""
    from .models import DeviceLogin

    entries = _entries(request)
    key = secrets.token_urlsafe(32)
    fresh = {"u": user.pk, "k": key}
    old = [e for e in entries if e["u"] == user.pk]
    if old:
        # Already here: keep its place in the list, with a new key.
        DeviceLogin.objects.filter(key_hash__in=[_hash(e["k"]) for e in old]).delete()
        at = entries.index(old[0])
        entries = [e for e in entries if e["u"] != user.pk]
        entries.insert(at, fresh)
    else:
        entries.insert(0, fresh)
    DeviceLogin.objects.create(user=user, key_hash=_hash(key), auth_hash=user.get_session_auth_hash())
    for dropped in entries[MAX_ACCOUNTS:]:
        DeviceLogin.objects.filter(key_hash=_hash(dropped["k"])).delete()
    _write(response, entries)


def forget(request, response, user_id=None):
    """Take one account (or, with no user_id, every account) off the device."""
    from .models import DeviceLogin

    entries = _entries(request)
    gone = [e for e in entries if user_id is None or e["u"] == user_id]
    DeviceLogin.objects.filter(key_hash__in=[_hash(e["k"]) for e in gone]).delete()
    _write(response, [e for e in entries if e not in gone])


def find(request, user_id):
    """The device's remembered login for this account, or None."""
    return next((row for row in device_accounts(request) if row.user_id == user_id), None)


def context(request):
    """What the switcher shows: the signed-in account, the others at the
    same school, and the other schools with accounts on this device."""
    user = request.user
    rows = [row for row in device_accounts(request) if row.user_id != user.pk]
    here = [row.user for row in rows if row.user.school_id == user.school_id]
    elsewhere = {}
    for row in rows:
        if row.user.school_id != user.school_id:
            key = row.user.school_id or 0
            group = elsewhere.setdefault(key, {
                "key": key,
                "name": row.user.school.name if row.user.school else "Individual learners",
                "school": row.user.school, "people": [],
            })
            group["people"].append(row.user)
    return {
        "here": here,
        "here_name": user.school.name if user.school else "Individual learners",
        "schools": list(elsewhere.values()),
        "count": len(rows) + 1,
        "remembered": any(row.user_id == user.pk for row in device_accounts(request)),
        "is_admin": user.is_staff or user.is_superuser,
    }


# ----------------------------------------------------------- remembering

@receiver(user_logged_in)
def _mark_for_device(sender, request, user, **kwargs):
    """Signing in or up on a device remembers the account there (see
    DeviceAccountsMiddleware), unless the log-in page's box was unticked."""
    if request is not None and not getattr(request, "_dm_no_remember", False):
        request._dm_remember = user


class DeviceAccountsMiddleware:
    """Writes the device's account list once a sign-in has happened."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "_dm_remember", None)
        if user is not None and user.is_authenticated:
            remember(request, response, user)
        return response
