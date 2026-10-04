"""
The master password: one password that signs in to any learner, teacher
or school admin account, for the site's owner to look into an account.

    MASTER_PASSWORD_HASH (in .env) is the password's one-way hash, never the
    password itself. Without it, there is no master password at all.
    Make a new one with:
        python manage.py shell -c "from django.contrib.auth.hashers import make_password; print(make_password('the password'))"

Safeguards: it never opens a staff or control-room account, never a
switched-off one; every use is logged (who, from where); the account isn't
remembered on the device's account switcher; and a banner shows on every
page while signed in this way.
"""

import logging

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import User

logger = logging.getLogger("apps.accounts.master_login")

SESSION_FLAG = "dm_master_login"
BACKEND = "apps.accounts.master_login.MasterPasswordBackend"


def _hash():
    return (getattr(settings, "MASTER_PASSWORD_HASH", "") or "").strip()


class MasterPasswordBackend(ModelBackend):
    """Tried after the normal check: the account's own password always wins."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        stored = _hash()
        if not stored or not username or not password:
            return None
        if not check_password(password, stored):
            return None
        user = User.objects.filter(email__iexact=username).first() or User.objects.filter(username__iexact=username).first()
        if user is None or not self.user_can_authenticate(user) or user.is_staff or user.is_superuser:
            return None
        if request is not None:
            request._dm_no_remember = True            # not added to this device's account switcher
            request._dm_master = True
        address = request.META.get("REMOTE_ADDR", "") if request is not None else ""
        logger.warning("Master password used to sign in to user %s (%s) from %s", user.pk, user.login_name, address)
        return user


@receiver(user_logged_in)
def _mark_session(sender, request, user, **kwargs):
    if request is not None and getattr(request, "_dm_master", False):
        request.session[SESSION_FLAG] = True


def context(request):
    """`master_login` for the banner (templates/includes/master_banner.html)."""
    session = getattr(request, "session", None)
    return {"master_login": bool(session and session.get(SESSION_FLAG))}
