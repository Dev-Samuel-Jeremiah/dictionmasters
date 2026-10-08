"""
An individual learner's scheme of work, at their own pace.

An individual has no school and no term dates, so they choose a level's
scheme (SchemeChoice) and work through it at their own pace: First Term,
then Second, then Third. Everything is open — they can move around the
terms, weeks and days as they like until the whole scheme is done. Their
dashboard shows the next lesson (the first not done, in order) and a
Lessons card; the Lessons page lays the scheme out term, week and day.
"Done" means the same as it does for school students (timetable.py), and
nothing else is closed to them: Learn stays open.

    follows_path(user)      an individual learner (not staff, not a child on
                            the simple home)
    choice_for(user)        their SchemeChoice, or None
    path(user, level)       every week with ticks, the current one, the next
                            lesson, and whether it's all done
    lessons(user, level)    the whole scheme as terms, weeks and days, for
                            the Lessons page
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
    in path order, state "done", "current" (the first not finished) or
    "todo". rows: the current week's lessons with ticks."""
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
            state = "done" if done == len(found) else "todo"
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
    """{(term, week)} the learner may open: all of them."""
    return {(w["term"], w["week"]) for w in path(user, level)["weeks"]}


def lessons(user, level):
    """The whole scheme for the Lessons page: {"terms", "done", "total",
    "current"}. terms: [{"number", "label", "done", "total", "weeks"}], each
    week {"week", "label", "done", "total", "is_current", "days"}, each day
    {"label", "rows"} Monday to Friday with "any day" first."""
    from .models import DAY_CHOICES, DAY_ORDER

    entries = list(_entries(level=level))
    done_ids = done_for([user], entries)[user.pk]
    state = path(user, level)
    current = state["current"]
    labels = dict(DAY_CHOICES)
    terms = {}
    for entry in _sorted(entries):
        term = terms.setdefault(entry.term, {"number": entry.term, "label": TERM_LABELS.get(entry.term, ""),
                                             "done": 0, "total": 0, "weeks": {}})
        week = term["weeks"].setdefault(entry.week, {
            "week": entry.week, "label": f"Week {entry.week}", "done": 0, "total": 0, "days": {},
            "is_current": bool(current) and (current["term"], current["week"]) == (entry.term, entry.week),
        })
        row = _row(entry, done_ids)
        day = week["days"].setdefault(entry.day, {"key": entry.day, "label": labels.get(entry.day) or "Any day this week",
                                                  "rows": []})
        day["rows"].append(row)
        for bucket in (term, week):
            bucket["total"] += 1
            bucket["done"] += row["done"]
    ordered = []
    for number in sorted(terms):
        term = terms[number]
        weeks = []
        for key in sorted(term["weeks"]):
            week = term["weeks"][key]
            week["days"] = sorted(week["days"].values(),
                                  key=lambda d: DAY_ORDER.index(d["key"]) if d["key"] in DAY_ORDER else 0)
            weeks.append(week)
        ordered.append({**term, "weeks": weeks})
    return {"terms": ordered, "current": current,
            "done": sum(t["done"] for t in ordered), "total": sum(t["total"] for t in ordered)}


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
