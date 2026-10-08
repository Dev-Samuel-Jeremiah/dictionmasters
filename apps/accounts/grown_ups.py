"""
The PIN on the For grown-ups page, so a child can't wander in and switch
the simple home off, or see the plan.

A grown-up sets a 4-digit PIN the first time. After that the page asks
for it and stays open on that device for UNLOCK_MINUTES (kept in the
session, the same way school logins unlock: apps/schools/logins.py).
After MAX_TRIES wrong PINs in a row, entering one is shut for
LOCK_MINUTES, wherever it's tried from. A forgotten PIN is replaced by
typing the account's password, which also covers a child who set one
before their grown-up did.

The PIN is hashed like a password and never shown.
"""

import logging
import re
import time
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import GrownUpSettings

logger = logging.getLogger("apps.accounts.grown_ups")

UNLOCK_MINUTES = 15
LOCK_MINUTES = 15
MAX_TRIES = 5
SESSION_KEY = "grown_ups_unlocked_until"
PIN_RE = re.compile(r"^\d{4}$")


def settings_for(user):
    found, _ = GrownUpSettings.objects.get_or_create(user=user)
    return found


def needs_pin(user):
    """The PIN is for children's accounts and the individual accounts
    that may be a child's; teachers and staff don't get one."""
    return not user.is_staff and (user.is_student or user.is_individual)


def has_pin(found):
    return bool(found.pin_hash)


def valid_pin(pin):
    return bool(PIN_RE.match(pin or ""))


def set_pin(request, found, pin):
    found.pin_hash = make_password(pin)
    found.failed_tries = 0
    found.locked_until = None
    found.save(update_fields=["pin_hash", "failed_tries", "locked_until"])
    _open(request)


def is_locked_out(found):
    return bool(found.locked_until and found.locked_until > timezone.now())


def try_pin(request, found, pin):
    """True and unlocked if the PIN is right. Wrong ones are counted, and
    the MAX_TRIES-th shuts PIN entry for LOCK_MINUTES."""
    if is_locked_out(found):
        return False
    if check_password(pin or "", found.pin_hash):
        found.failed_tries = 0
        found.save(update_fields=["failed_tries"])
        _open(request)
        return True
    found.failed_tries += 1
    if found.failed_tries >= MAX_TRIES:
        found.failed_tries = 0
        found.locked_until = timezone.now() + timedelta(minutes=LOCK_MINUTES)
        logger.warning("For grown-ups: PIN locked after %s wrong tries for user %s", MAX_TRIES, found.user_id)
    found.save(update_fields=["failed_tries", "locked_until"])
    return False


def reset_with_password(request, found, password, pin):
    """A forgotten PIN: the account's password lets a new one be set."""
    if not found.user.check_password(password or ""):
        logger.warning("For grown-ups: wrong password resetting the PIN for user %s", found.user_id)
        return False
    set_pin(request, found, pin)
    return True


def _open(request):
    # Tied to the account, so on a family device shared through the
    # account switcher one child's unlock never opens a sibling's page.
    request.session[SESSION_KEY] = {"user": request.user.pk, "until": time.time() + UNLOCK_MINUTES * 60}


def is_unlocked(request):
    opened = request.session.get(SESSION_KEY) or {}
    return isinstance(opened, dict) and opened.get("user") == request.user.pk and opened.get("until", 0) > time.time()


def lock(request):
    request.session.pop(SESSION_KEY, None)
