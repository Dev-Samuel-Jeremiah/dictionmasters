"""
How a teacher's class is getting on, read from what each tool already
records: EchoSpell attempts and completed groups, module days,
assessments, Clash games and Yela readings.

Every number is gathered for the whole class at once — one grouped query
per tool, never one per pupil — so a class of 40 costs the same as a
class of 4. It only reads; nothing here changes anyone's progress.

The 44 Academy and Tricks to Sound Fluent are left out: their progress is
worked out a learner at a time (apps/tricks/progress.py), which a class
view can't afford.

The same rows feed the weekly summary for grown-ups and the teacher's
"Needs help" list and email (apps/accounts/weekly.py), so all three tell
the same story. A pupil needs help when they've tried one activity
STUCK_TRIES times in STUCK_DAYS without passing it, or gone quiet.
"""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.assessments.models import Attempt as AssessmentAttempt
from apps.clash.models import Match
from apps.echospell.models import ActivityAttempt, Group, GroupProgress
from apps.learning_modules.models import DayProgress
from apps.tutor.models import TutorSession

# Tried the same activity this many times in STUCK_DAYS without passing:
# the pupil needs help with it.
STUCK_TRIES = 3
STUCK_DAYS = 14

# A pupil with nothing done in this many days (today included) is shown
# as quiet; the same days make up "this week".
QUIET_DAYS = 7


def _week_start(now):
    """The start of the day six days ago: the same seven days as the
    learner's own "This week" chart."""
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=QUIET_DAYS - 1)


def _activity(queryset, when, since, **extra):
    """{pupil id: {"last": ..., "week": ..., **extra}} for one tool."""
    rows = queryset.values("user").annotate(
        last=Max(when), week=Count("pk", filter=Q(**{f"{when}__gte": since})), **extra
    )
    return {row.pop("user"): row for row in rows}


def class_progress(pupils, now=None):
    """Rows for each pupil, and the class's totals.

    `pupils` is a queryset of learners: a teacher's students
    (access.pupils_of), or a batch of accounts for the weekly emails."""
    now = now or timezone.now()
    since = _week_start(now)
    pupils = list(pupils.order_by("first_name", "last_name", "pk"))
    ids = [p.pk for p in pupils]

    finished_match = Coalesce("finished_at", "started_at")
    sources = [
        _activity(
            ActivityAttempt.objects.filter(user__in=ids), "created_at", since,
            activity_avg=Avg("percent", filter=Q(status__in=["marked", "reviewed"])),
            activity_avg_week=Avg("percent", filter=Q(status__in=["marked", "reviewed"], created_at__gte=since)),
            activities_waiting=Count("pk", filter=Q(status="awaiting")),
        ),
        _activity(GroupProgress.objects.filter(user__in=ids), "completed_at", since),
        _activity(DayProgress.objects.filter(user__in=ids), "completed_at", since, days=Count("pk")),
        _activity(
            AssessmentAttempt.objects.filter(user__in=ids).exclude(submitted_at=None), "submitted_at", since,
            assessment_avg=Avg("percent", filter=Q(status__in=["submitted", "marked"])),
            to_mark=Count("pk", filter=Q(status=AssessmentAttempt.Status.AWAITING)),
        ),
        _activity(
            Match.objects.filter(user__in=ids, status=Match.Status.FINISHED).annotate(ended=finished_match),
            "ended", since,
        ),
        _activity(
            TutorSession.objects.filter(user__in=ids, status=TutorSession.STATUS_DONE), "finished_at", since,
            readings=Count("pk"),
        ),
    ]

    # EchoSpell: groups done in the pupil's own level, out of that level's groups.
    level_totals = dict(
        Group.objects.filter(level__is_published=True).values_list("level__name").annotate(n=Count("pk"))
    )
    done_by_level = {
        (user, level): n
        for user, level, n in GroupProgress.objects.filter(user__in=ids, group__level__is_published=True)
        .values_list("user", "group__level__name").annotate(n=Count("pk"))
    }

    # Stuck: tried one activity again and again lately, never passed it.
    stuck = {}
    tried = (
        ActivityAttempt.objects.filter(user__in=ids).exclude(status="awaiting")
        .values("user", "activity", "activity__title")
        .annotate(
            tries=Count("pk", filter=Q(created_at__gte=now - timedelta(days=STUCK_DAYS))),
            passes=Count("pk", filter=Q(passed=True)),
        )
        .filter(tries__gte=STUCK_TRIES, passes=0)
        .order_by("activity__title")
    )
    for row in tried:
        stuck.setdefault(row["user"], []).append({"title": row["activity__title"], "tries": row["tries"]})

    rows = []
    for pupil in pupils:
        found = [source.get(pupil.pk, {}) for source in sources]
        lasts = [f["last"] for f in found if f.get("last")]
        merged = {}
        for f in found:
            merged.update({k: v for k, v in f.items() if k not in ("last", "week") and v is not None})
        last = max(lasts) if lasts else None
        total = level_totals.get(pupil.level, 0)
        done = done_by_level.get((pupil.pk, pupil.level), 0)
        # The per-tool counts for the week, in `sources` order.
        weeks = [f.get("week", 0) for f in found]
        state = "new" if last is None else "quiet" if last < since else "active"
        stuck_on = stuck.get(pupil.pk, [])
        rows.append({
            "pupil": pupil,
            "last_active": last,
            "just_now": last is not None and now - last < timedelta(minutes=1),
            "sessions_week": sum(f.get("week", 0) for f in found),
            "state": state,
            "echospell_done": done,
            "echospell_total": total,
            "echospell_percent": round(done * 100 / total) if total else 0,
            "activity_avg": round(merged["activity_avg"]) if "activity_avg" in merged else None,
            "assessment_avg": round(merged["assessment_avg"]) if "assessment_avg" in merged else None,
            "to_mark": merged.get("to_mark", 0),
            "module_days": merged.get("days", 0),
            "readings": merged.get("readings", 0),
            "week": {
                "activities": weeks[0], "groups": weeks[1], "days": weeks[2], "assessments": weeks[3],
                "games": weeks[4], "readings": weeks[5],
                "activity_avg": round(merged["activity_avg_week"]) if "activity_avg_week" in merged else None,
            },
            "activities_waiting": merged.get("activities_waiting", 0),
            "stuck_on": stuck_on,
            "needs_help": bool(stuck_on) or state == "quiet",
        })

    return {
        "rows": rows,
        "summary": {
            "pupils": len(rows),
            "active": sum(1 for r in rows if r["state"] == "active"),
            "quiet": sum(1 for r in rows if r["state"] == "quiet"),
            "new": sum(1 for r in rows if r["state"] == "new"),
            "to_mark": sum(r["to_mark"] for r in rows),
            "needs_help": sum(1 for r in rows if r["needs_help"]),
        },
        "quiet_days": QUIET_DAYS,
    }
