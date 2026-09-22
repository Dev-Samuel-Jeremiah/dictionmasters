"""
Everything the learner dashboard shows, gathered from each tool.

Each tool keeps its own record of what a learner has done — EchoSpell
attempts and completed groups, module days, assessment attempts, Clash
games. This module reads them into one picture: a study streak, the
week's activity, where to carry on, and a feed of recent work. It only
reads; nothing here changes anyone's progress.
"""

from datetime import timedelta

from django.db.models import Avg, Max
from django.urls import reverse
from django.utils import timezone

from apps.assessments.models import Attempt as AssessmentAttempt
from apps.book.models import ACADEMY, TRICKS, Sound
from apps.clash.models import Match
from apps.echospell.models import ActivityAttempt, CardPosition, Group, GroupProgress
from apps.learning_modules.models import Day, DayProgress
from apps.quick_words.models import QuickWord

from .access import limit_to_levels

FEED_SIZE = 6
WEEK = 7
# The sounds circling the hero's cube — the ones learners find hardest.
ORBIT_SYMBOLS = ["θ", "ð", "ʃ", "ŋ", "æ", "ʒ", "ɜː", "ʊ"]


def _local_date(moment):
    return timezone.localtime(moment).date()


def _events(user):
    """(when, kind, title, detail, url) for everything the learner has
    done, newest first. Kept small: only what the feed and charts need."""
    events = []

    for attempt in ActivityAttempt.objects.filter(user=user).select_related(
        "activity__group__level"
    )[:200]:
        group = attempt.activity.group
        events.append((
            attempt.created_at, "echospell", attempt.activity.title,
            f"{group.level.name} · Group {group.number} · {attempt.percent}%",
            reverse("echospell:activity_result", args=[group.level.slug, group.slug, attempt.activity.slug, attempt.pk]),
        ))

    for done in GroupProgress.objects.filter(user=user).select_related("group__level").order_by("-completed_at")[:200]:
        events.append((
            done.completed_at, "echospell", f"Completed Group {done.group.number}",
            done.group.level.name,
            reverse("echospell:group_detail", args=[done.group.level.slug, done.group.slug]),
        ))

    for done in DayProgress.objects.filter(user=user).select_related("day__week__term__module").order_by("-completed_at")[:200]:
        day = done.day
        week, term = day.week, day.week.term
        events.append((
            done.completed_at, "modules", f"{term.module.name}: {day.get_day_name_display()}",
            f"{term.name} · {week.display_name}",
            reverse("learning_modules:day_detail", args=[term.module.slug, term.slug, week.slug, day.day_name]),
        ))

    for attempt in AssessmentAttempt.objects.filter(user=user).exclude(submitted_at=None).select_related("assessment")[:200]:
        events.append((
            attempt.submitted_at, "assessments", attempt.assessment.title,
            f"{attempt.get_status_display()}" + (f" · {attempt.percent}%" if attempt.status != "awaiting" else ""),
            reverse("assessments:hub"),
        ))

    for match in Match.objects.filter(user=user, status=Match.Status.FINISHED)[:200]:
        events.append((
            match.finished_at or match.started_at, "clash", f"{match.mode_spec.label}",
            f"{match.tier.label} · {match.score} points",
            reverse("clash:result", args=[match.pk]),
        ))

    events.sort(key=lambda e: e[0], reverse=True)
    return events


def _streak(active_days, today):
    """Days in a row with some practice. A streak survives until the end
    of today, so yesterday's practice still counts this morning."""
    day = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while day in active_days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _best_streak(active_days):
    best = run = 0
    previous = None
    for day in sorted(active_days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def _week(events, today):
    counts = {today - timedelta(days=offset): 0 for offset in range(WEEK)}
    for when, *_ in events:
        day = _local_date(when)
        if day in counts:
            counts[day] += 1
    top = max(counts.values()) or 1
    return [
        {
            "label": day.strftime("%a"),
            "count": counts[day],
            "height": max(6, round(counts[day] * 100 / top)) if counts[day] else 4,
            "is_today": day == today,
        }
        for day in sorted(counts)
    ]


def _echospell_resume(user):
    """The EchoSpell card page — and the exact card on it — the learner
    was last on, if they can still open it."""
    position = CardPosition.objects.filter(user=user).select_related("group__level", "category", "lesson").first()
    if position is None:
        return None
    group, category, lesson = position.group, position.category, position.lesson
    still_open = (
        group.level.is_published
        and limit_to_levels(Group.objects.filter(pk=group.pk), user, field="level__name", allow_blank=False).exists()
        and group.level.categories.filter(pk=category.pk).exists()
    )
    if not still_open:
        return None
    url = reverse("echospell:card_detail", args=[group.level.slug, group.slug, category.slug])
    if lesson and lesson.is_published and lesson.group_id == group.pk and lesson.category_id == category.pk:
        url += f"#card-{lesson.pk}"
    return {"group": group, "category": category, "url": url}


def _next_echospell(user):
    done = set(GroupProgress.objects.filter(user=user).values_list("group_id", flat=True))
    groups = limit_to_levels(
        Group.objects.filter(level__is_published=True), user, field="level__name", allow_blank=False
    ).select_related("level").order_by("level__order", "level__name", "number")
    total = 0
    upcoming = None
    for group in groups:
        total += 1
        if upcoming is None and group.pk not in done:
            upcoming = group
    completed = len(done & set(g.pk for g in groups))
    return {
        "group": upcoming,
        "url": reverse("echospell:group_detail", args=[upcoming.level.slug, upcoming.slug]) if upcoming else reverse("echospell:hub"),
        "resume": _echospell_resume(user),
        "completed": completed,
        "total": total,
        "percent": round(completed * 100 / total) if total else 0,
    }


def _next_module_day(user):
    done = set(DayProgress.objects.filter(user=user).values_list("day_id", flat=True))
    days = list(
        Day.objects.filter(is_published=True, week__term__module__is_published=True)
        .select_related("week__term__module")
        .order_by("week__term__module__order", "week__term__module__name", "week__term__order", "week__term__id", "week__number", "order", "id")
    )
    upcoming = next((d for d in days if d.pk not in done), None)
    completed = sum(1 for d in days if d.pk in done)
    result = {
        "day": upcoming,
        "url": reverse("learning_modules:hub"),
        "completed": completed,
        "total": len(days),
        "percent": round(completed * 100 / len(days)) if days else 0,
    }
    if upcoming:
        week, term = upcoming.week, upcoming.week.term
        result["url"] = reverse("learning_modules:day_detail", args=[term.module.slug, term.slug, week.slug, upcoming.day_name])
    return result


def learner_dashboard(user):
    now = timezone.now()
    today = _local_date(now)
    events = _events(user)
    active_days = {_local_date(e[0]) for e in events}

    matches = Match.objects.filter(user=user, status=Match.Status.FINISHED)
    clash = matches.aggregate(best=Max("score"))
    marked = AssessmentAttempt.objects.filter(user=user, status__in=["submitted", "marked"])
    echospell_attempts = ActivityAttempt.objects.filter(user=user, status__in=["marked", "reviewed"])

    hour = timezone.localtime(now).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

    week = _week(events, today)
    return {
        "orbit_symbols": ORBIT_SYMBOLS,
        "greeting": greeting,
        "today": today,
        "streak": _streak(active_days, today),
        "best_streak": _best_streak(active_days),
        "practised_today": today in active_days,
        "week": week,
        "week_total": sum(d["count"] for d in week),
        "echospell": _next_echospell(user),
        "modules": _next_module_day(user),
        "academy_sounds": Sound.objects.in_programme(ACADEMY).filter(is_published=True).count(),
        "tricks_count": Sound.objects.in_programme(TRICKS).filter(is_published=True).count(),
        "tricks_done": _lessons_done(user, TRICKS),
        "academy_done": _lessons_done(user, ACADEMY),
        "clash_best": clash["best"],
        "clash_games": matches.count(),
        "assessment_average": round(marked.aggregate(avg=Avg("percent"))["avg"] or 0) if marked.exists() else None,
        "assessments_taken": marked.count(),
        "activity_average": round(echospell_attempts.aggregate(avg=Avg("percent"))["avg"] or 0) if echospell_attempts.exists() else None,
        "activities_done": echospell_attempts.count(),
        "saved_words": QuickWord.objects.filter(lists__user=user).distinct().count(),
        "level": (user.level or "").strip(),
        "feed": [
            {"when": when, "recent": now - when < timedelta(minutes=1), "kind": kind, "title": title, "detail": detail, "url": url}
            for when, kind, title, detail, url in events[:FEED_SIZE]
        ],
    }


def _lessons_done(user, programme):
    """How many of a programme's lessons this learner has completed —
    worked through and passed the assessment of."""
    from apps.tricks.progress import Standing

    return Standing(user, programme).done
