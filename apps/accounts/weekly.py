"""
The week, told to the grown-ups: a summary for each learner, and for
each teacher the pupils who need help.

    summary_lines(row)     the week in a few lines, from a class_progress row
    learner_summary(user)  the same for one learner, for the For grown-ups page
    send_weekly(...)       the Monday emails (manage.py send_weekly_summaries)

Every number comes from apps/schools/class_progress.py, gathered a batch
of BATCH learners at a time — a fixed number of queries per batch, never
one per learner. Emails go only to accounts with an email of their own,
that haven't switched them off, and that weren't sent one in the last
few days, so running the command twice in a week sends nothing new.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.schools.class_progress import QUIET_DAYS, class_progress

from .access import is_pupil_of
from .models import INTERNAL_EMAIL_DOMAIN, GrownUpSettings, User

logger = logging.getLogger("apps.accounts.weekly")

BATCH = 500
# Sent less than this long ago: this week's has already gone.
RESEND_AFTER = timedelta(days=6)


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def summary_lines(row):
    """(title, text) lines for a learner's week."""
    week = row["week"]
    lines = [("Practice", f"{_plural(row['sessions_week'], 'session')} this week."
              if row["sessions_week"] else "No practice yet this week. A few minutes a day makes a big difference.")]
    finished = [part for part in (
        _plural(week["groups"], "EchoSpell group") if week["groups"] else "",
        _plural(week["days"], "module day") if week["days"] else "",
    ) if part]
    if finished:
        lines.append(("Lessons finished", " and ".join(finished) + "."))
    if week["activity_avg"] is not None:
        lines.append(("Scores", f"{week['activity_avg']}% on average across {_plural(week['activities'], 'activity', 'activities')}."))
    waiting = row["activities_waiting"] + row["to_mark"]
    if waiting:
        lines.append(("Waiting for the teacher", f"{_plural(waiting, 'recording or answer', 'recordings and answers')} sent for marking."))
    if row["stuck_on"]:
        names = ", ".join(f"{s['title']} ({s['tries']} tries)" for s in row["stuck_on"][:3])
        lines.append(("Could use a hand with", names + "."))
    return lines


def help_reason(row):
    """Why a pupil is on the teacher's "Needs help" list, in a line."""
    if row["stuck_on"]:
        first = row["stuck_on"][0]
        more = f" and {_plural(len(row['stuck_on']) - 1, 'other')}" if len(row["stuck_on"]) > 1 else ""
        return f"Stuck on {first['title']}: {first['tries']} tries, not passed yet{more}."
    return f"Nothing done in the last {QUIET_DAYS} days."


def learner_summary(user):
    row = class_progress(User.objects.filter(pk=user.pk))["rows"][0]
    return {"row": row, "lines": summary_lines(row)}


# ---------------------------------------------------------------------------
# The Monday emails
# ---------------------------------------------------------------------------

def _site():
    return (getattr(settings, "SITE_URL", "") or "").rstrip("/")


def _email(user, subject, context):
    context = {"site_url": _site(), **context}
    text = render_to_string("accounts/email/weekly.txt", context)
    html = render_to_string("accounts/email/weekly.html", context)
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
    message.attach_alternative(html, "text/html")
    return message


def learner_email(row):
    pupil = row["pupil"]
    name = pupil.first_name or "Your learner"
    return _email(pupil, f"{name}'s week on Diction Masters", {
        "eyebrow": "This week",
        "headline": f"{name}'s week",
        "intro": "Here's how the week went on Diction Masters.",
        "lines": summary_lines(row),
        "cta": "Open For grown-ups",
        "cta_url": _site() + reverse("accounts:grown_ups"),
        "footer": "You can switch these weekly emails off on the For grown-ups page.",
    })


def teacher_email(teacher, rows):
    return _email(teacher, f"{_plural(len(rows), 'pupil')} could use your help this week", {
        "eyebrow": "Needs help",
        "headline": f"{_plural(len(rows), 'pupil')} could use your help",
        "intro": "These pupils are stuck on an activity or have gone quiet. A quick word can get them going again.",
        "lines": [(r["pupil"].get_full_name() or r["pupil"].login_name, help_reason(r)) for r in rows],
        "cta": "Open My class",
        "cta_url": _site() + reverse("schools:class_dashboard"),
        "footer": "You can switch this weekly email off on the My class page.",
    })


def _due(queryset, now):
    """Accounts with an inbox of their own that want this week's email and
    haven't had it."""
    return (
        queryset.filter(is_active=True, is_staff=False)
        .exclude(email__endswith="@" + INTERNAL_EMAIL_DOMAIN)
        .exclude(grown_up__weekly_email=False)
        .exclude(grown_up__last_summary_at__gte=now - RESEND_AFTER)
    )


def _batches(queryset):
    ids = list(queryset.order_by("pk").values_list("pk", flat=True))
    for start in range(0, len(ids), BATCH):
        yield User.objects.filter(pk__in=ids[start:start + BATCH])


def _deliver(messages, dry_run):
    if dry_run or not messages:
        return len(messages)
    try:
        return get_connection().send_messages(messages) or 0
    except Exception:
        logger.exception("Weekly emails: a batch of %s couldn't be sent", len(messages))
        return 0


def _mark_sent(user_ids, now):
    GrownUpSettings.objects.bulk_create([GrownUpSettings(user_id=pk) for pk in user_ids], ignore_conflicts=True)
    GrownUpSettings.objects.filter(user_id__in=user_ids).update(last_summary_at=now)


def send_weekly(now=None, dry_run=False, out=None):
    """Send this week's emails. Returns {"learners": n, "teachers": n}."""
    now = now or timezone.now()
    say = out or (lambda line: None)
    sent = {"learners": 0, "teachers": 0}

    # Learners: their own summary.
    learners = _due(User.objects.filter(role__in=[User.Role.STUDENT, User.Role.INDIVIDUAL]), now)
    for batch in _batches(learners):
        rows = class_progress(batch, now=now)["rows"]
        messages = [learner_email(row) for row in rows]
        for row in rows:
            say(f"summary → {row['pupil'].email}")
        delivered = _deliver(messages, dry_run)
        if not dry_run and delivered:
            _mark_sent([row["pupil"].pk for row in rows], now)
        sent["learners"] += delivered

    # Teachers: the pupils of theirs who need help, if any.
    teachers = list(_due(User.objects.filter(role=User.Role.TEACHER, school__isnull=False), now))
    if teachers:
        stuck = []
        students = User.objects.filter(role=User.Role.STUDENT, is_active=True,
                                       school__in={t.school_id for t in teachers})
        for batch in _batches(students):
            stuck += [row for row in class_progress(batch, now=now)["rows"] if row["needs_help"]]
        messages, told = [], []
        for teacher in teachers:
            theirs = [row for row in stuck if is_pupil_of(teacher, row["pupil"])]
            if theirs:
                messages.append(teacher_email(teacher, theirs))
                told.append(teacher.pk)
                say(f"needs help → {teacher.email} ({len(theirs)})")
        delivered = _deliver(messages, dry_run)
        if not dry_run and delivered:
            _mark_sent(told, now)
        sent["teachers"] += delivered
    return sent
