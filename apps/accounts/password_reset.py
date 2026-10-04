"""
Forgotten passwords, for every kind of account.

    Someone with an email of their own (a school admin, a teacher, an
    individual learner, many students) is emailed a link that lets them
    choose a new password. It works once, and for an hour
    (PASSWORD_RESET_TIMEOUT); setting the password — or signing in — makes
    it stop working.

    Someone who signs in with a username and has no email (a student whose
    school made their account) can't be emailed, so their school admin is
    asked instead: a "password help" request appears on the school
    dashboard, where the admin gives them a new password (apps/schools/
    logins.py). With no school, it waits in the control room for staff.

The form answers the same way whether or not an account matched, so it
can't be used to find out who has an account, and it's rate-limited by
address and by account.
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import PasswordHelpRequest, User

logger = logging.getLogger("apps.accounts.password_reset")

PER_ADDRESS_HOUR = 10       # forgot-password requests from one IP address in an hour
PER_ACCOUNT_HOUR = 3        # emails or help requests for one account in an hour


def find_account(typed):
    """The active account an email or username belongs to, or None —
    matched the same way the log-in form matches them."""
    typed = (typed or "").strip()
    if not typed:
        return None
    people = User.objects.filter(is_active=True)
    if "@" not in typed:
        found = people.filter(username__iexact=typed).first()
        if found:
            return found
    return people.filter(email__iexact=typed).first()


def _over_limit(key, limit):
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, 60 * 60)
    return False


def address_over_limit(request):
    ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
          or request.META.get("REMOTE_ADDR", "")) or "unknown"
    return _over_limit(f"pw-forgot:ip:{ip}", PER_ADDRESS_HOUR)


def site_url(request):
    return (getattr(settings, "SITE_URL", "") or request.build_absolute_uri("/")).rstrip("/")


def reset_link(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return site_url(request) + reverse("accounts:password_reset_confirm", args=[uid, token])


def send_reset_email(request, user):
    context = {
        "user": user,
        "link": reset_link(request, user),
        "hours": max(1, round(getattr(settings, "PASSWORD_RESET_TIMEOUT", 3600) / 3600)),
        "site_url": site_url(request),
        "login_name": user.login_name,
    }
    subject = "Reset your Diction Masters password"
    text = render_to_string("accounts/email/password_reset.txt", context)
    html = render_to_string("accounts/email/password_reset.html", context)
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
    message.attach_alternative(html, "text/html")
    try:
        message.send()
    except Exception:
        logger.exception("Password reset email to user %s couldn't be sent", user.pk)
        return False
    logger.info("Password reset email sent to user %s", user.pk)
    return True


def ask_for_help(user):
    """A password help request for someone with no email, once a day at most."""
    since = timezone.now() - timezone.timedelta(days=1)
    open_request = PasswordHelpRequest.objects.filter(user=user, resolved_at__isnull=True, created_at__gte=since).first()
    if open_request:
        return open_request
    logger.info("Password help requested for user %s", user.pk)
    return PasswordHelpRequest.objects.create(user=user, school=user.school)


def start(request, typed):
    """Do whatever suits the account typed in. Returns what happened, for
    logs and tests only — the page says the same thing either way:
    "emailed", "asked_school", "asked_staff", "limited" or "none"."""
    user = find_account(typed)
    if user is None:
        logger.info("Forgot password: no active account matched what was typed")
        return "none"
    if _over_limit(f"pw-forgot:user:{user.pk}", PER_ACCOUNT_HOUR):
        return "limited"
    if user.has_real_email:
        send_reset_email(request, user)
        return "emailed"
    ask_for_help(user)
    return "asked_school" if user.school_id else "asked_staff"


def resolve(user, by=None):
    """A new password has been set: their help requests are done."""
    PasswordHelpRequest.objects.filter(user=user, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolved_by=by)


def open_requests(school):
    return (PasswordHelpRequest.objects.filter(school=school, resolved_at__isnull=True, user__is_active=True)
            .select_related("user").order_by("-created_at"))
