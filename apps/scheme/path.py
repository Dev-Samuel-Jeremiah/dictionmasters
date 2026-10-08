"""
An individual learner's scheme of work, at their own pace.

An individual has no school and no term dates, so they choose a level's
scheme (SchemeChoice) and work through it as one path: First Term's weeks,
then Second, then Third. A week opens once every lesson of the week
before it is done, so they go as fast or as slow as they like. Their
dashboard shows the next lesson and a My weeks card, the same shape as a
school student's (timetable.py); "done" means the same as it does there.
Unlike school students, nothing else is closed to them: Learn stays open.

    follows_path(user)      an individual learner (not staff, not a child on
                            the simple home)
    choice_for(user)        their SchemeChoice, or None
    path(user, level)       every week with ticks, the current one, the next
                            lesson, and whether it's all done
    schemes_on_offer()      each level with a live scheme, for choosing
"""

from django.db.models import Count

from .models import TERM_CHOICES, SchemeChoice, SchemeEntry
from .timetable import _entries, _row, _sorted, done_for

TERM_LABELS = dict(TERM_CHOICES)


def follows_path(user):
    return bool(
        getattr(user, "is_authenticated", False) and user.is_individual and not user.is_staff
        and not user.simple_home
    )


def choice_for(user):
    return SchemeChoice.objects.filter(user=user).first()


def _label(term, week):
    return f"{TERM_LABELS.get(term, '')}, Week {week}"


def path(user, level):
    """{"weeks", "current", "rows", "next", "complete", "done", "total"}.

    weeks: [{"term", "week", "label", "number", "done", "total", "state"}]
    in path order, state "done", "current" or "locked". rows: the current
    week's lessons with ticks."""
    entries = list(_entries(level=level))
    done_ids = done_for([user], entries)[user.pk]
    by_week = {}
    for entry in entries:
        by_week.setdefault((entry.term, entry.week), []).append(entry)
    weeks, current = [], None
    for number, key in enumerate(sorted(by_week), start=1):
        found = by_week[key]
        done = sum(1 for e in found if e.pk in done_ids)
        if current is None and done < len(found):
            state = "current"
            current = key
        else:
            state = "done" if current is None else "locked"
        weeks.append({"term": key[0], "week": key[1], "label": _label(*key), "number": number,
                      "done": done, "total": len(found), "state": state})
    rows = [_row(e, done_ids) for e in _sorted(by_week.get(current, []))]
    return {
        "weeks": weeks,
        "current": next((w for w in weeks if w["state"] == "current"), None),
        "rows": rows,
        "next": next((r for r in rows if not r["done"]), None),
        "complete": bool(weeks) and current is None,
        "done": sum(1 for r in rows if r["done"]),
        "total": len(rows),
    }


def open_weeks(user, level):
    """{(term, week)} the learner may open: every week up to the current one."""
    return {(w["term"], w["week"]) for w in path(user, level)["weeks"] if w["state"] != "locked"}


def schemes_on_offer():
    """[{"level", "weeks", "lessons"}] for every level with a live scheme, in
    the site's level order."""
    from apps.accounts.access import LEVEL_ORDER

    live = SchemeEntry.objects.filter(is_draft=False).order_by()      # no default ordering in these
    lessons = dict(live.values_list("level").annotate(n=Count("pk")))
    weeks = {}
    for level, term, week in live.values_list("level", "term", "week").distinct():
        weeks[level] = weeks.get(level, 0) + 1
    return [{"level": level, "weeks": weeks.get(level, 0), "lessons": lessons[level]}
            for level in sorted(lessons, key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else 99)]


def suggested_level(user):
    """The level a placement test recommended, if they've sat one."""
    from apps.assessments.models import Attempt

    found = (Attempt.objects.filter(user=user, assessment__kind="placement").exclude(recommended_level="")
             .order_by("-submitted_at").values_list("recommended_level", flat=True).first())
    return found or ""
