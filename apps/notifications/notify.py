"""
Making updates, and who they're for.

    notify(user, kind, title, body, url, key)       one update for one person
    notify_many(users, kind, title, body, url, key) the same for many, in one go
    teachers_of(student)   the teachers of the student's class
    admins_of(school)      the school's admins

Never raises: a failed update must never stop the thing that caused it
(a test being marked, someone signing up).
"""

import contextlib
import contextvars
import logging

from django.db import transaction

logger = logging.getLogger("apps.notifications")

_quiet = contextvars.ContextVar("notifications_quiet", default=False)


@contextlib.contextmanager
def quiet():
    """No updates while this runs: for bulk tools (bulk add, school sign-up
    with a whole roster), where one update per person would bury the rest."""
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


def notify(user, kind, title, body="", url="", key=""):
    return notify_many([user], kind, title, body, url, key)


def notify_many(users, kind, title, body="", url="", key=""):
    from .models import Notification

    if _quiet.get():
        return 0
    rows = [Notification(user_id=getattr(u, "pk", u), kind=kind, title=title[:200], body=body[:300],
                         url=url[:300], key=key[:120])
            for u in users if u is not None]
    if not rows:
        return 0
    try:
        with transaction.atomic():
            made = Notification.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
        from .reminders import forget

        for row in rows:
            forget(row.user_id)
        return len(made)
    except Exception:                             # an update must never break what caused it
        logger.exception("Couldn't save notification %r", title)
        return 0


def teachers_of(student):
    """The teachers of the student's class (apps/schools/models.SchoolClass)."""
    if not getattr(student, "school_class_id", None):
        return []
    from apps.schools.models import SchoolClass

    return list(SchoolClass.teachers.through.objects.filter(schoolclass_id=student.school_class_id)
                .values_list("user_id", flat=True))


def admins_of(school_id):
    from apps.accounts.models import User

    if not school_id:
        return []
    return list(User.objects.filter(school_id=school_id, role=User.Role.SCHOOL_ADMIN, is_active=True)
                .values_list("pk", flat=True))


def name_of(user):
    return user.get_full_name() or user.first_name or getattr(user, "login_name", "") or "Someone"
