"""
A school admin looking after their teachers' and students' logins:
seeing a login, resetting a password, and downloading login sheets.

Passwords themselves are only ever stored as one-way hashes. A separate
encrypted copy (apps/accounts/credentials.py) is what lets a school's
current passwords be shown again. Accounts whose password predates that
copy show as "not available" — giving them a new password fixes that.

Showing or resetting passwords needs the admin to confirm their own
password first; that unlocks these tools for UNLOCK_MINUTES, so an
unattended dashboard doesn't give logins away. Every view of a password,
reset and download is written to the log.
"""

import logging
import time

from django.conf import settings

from apps.accounts.credentials import decrypt_login_password
from apps.accounts.models import User

logger = logging.getLogger("apps.schools.logins")

UNLOCK_MINUTES = 15
SESSION_KEY = "school_logins_unlocked_until"
UNAVAILABLE = "Not available — reset to give a new one"


def unlock(request, password):
    """True if the admin's own password is right; unlocks for a while."""
    if not request.user.check_password(password or ""):
        logger.warning("School logins: wrong password from admin %s", request.user.pk)
        return False
    request.session[SESSION_KEY] = time.time() + UNLOCK_MINUTES * 60
    return True


def is_unlocked(request):
    return request.session.get(SESSION_KEY, 0) > time.time()


def minutes_left(request):
    return max(0, round((request.session.get(SESSION_KEY, 0) - time.time()) / 60))


def lock(request):
    request.session.pop(SESSION_KEY, None)


def members(admin, role=None, level=None, ids=None):
    """Active teachers and students of the admin's own school, never anyone else."""
    from apps.accounts import access

    people = User.objects.filter(school=admin.school, is_active=True, is_staff=False, is_superuser=False,
                                 role__in=(User.Role.TEACHER, User.Role.STUDENT))
    if role in (User.Role.TEACHER, User.Role.STUDENT):
        people = people.filter(role=role)
    if level:
        people = access.in_level(people, level)
    if ids is not None:
        people = people.filter(pk__in=ids)
    return people.order_by("role", "level", "first_name", "last_name", "pk")


def password_of(member):
    """The member's current password, or None if it can't be shown."""
    return decrypt_login_password(member.encrypted_login_password)


def reset(admin, member, password=""):
    """Give `member` a new password (one that's easy to type, unless the
    admin chose one) and return it. They're signed out everywhere, and
    taken off any family device's account switcher."""
    from apps.manage.bulk_students import new_password

    password = (password or "").strip() or new_password()
    member.set_password(password)
    member.save(update_fields=["password", "encrypted_login_password"])
    member.device_logins.all().delete()
    logger.info("School logins: admin %s reset the password of %s", admin.pk, member.pk)
    return password


def accounts(people, passwords=None):
    """Rows for a login sheet: each person with their password (a newly set
    one from `passwords`, else their current one)."""
    passwords = passwords or {}
    rows = []
    for person in people:
        password = passwords.get(person.pk) or password_of(person)
        rows.append({"user": person, "password": password or UNAVAILABLE, "password_available": bool(password)})
    return rows


def sheet(request, rows, title="Current logins", note=None):
    """(bytes, file name) of an Excel login sheet."""
    from apps.manage import bulk_students as bulk

    site_url = (getattr(settings, "SITE_URL", "") or request.build_absolute_uri("/")).rstrip("/")
    content, filename = bulk.school_logins_file(request.user.school, rows, site_url, note=note, title=title)
    logger.info("School logins: admin %s downloaded %s login(s) (%s)", request.user.pk, len(rows), title)
    return content, filename


def recovery_ready():
    return bool(getattr(settings, "SCHOOL_CREDENTIALS_ENCRYPTION_KEY", ""))
