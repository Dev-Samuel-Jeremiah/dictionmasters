"""
The scheme of work, from a student's side: what they see, and what they
may open.

A student at a school with a level follows the scheme (on_scheme). They
see this week's entries for their level — today's first — and can go back
to any week they have already reached; weeks still to come are hidden, and
their content can't be opened (gate.py). A level with no entries this term
gets an empty page saying so: the scheme alone decides what a student sees.

    on_scheme(user)                does this student follow the scheme?
    reached(user, today)           this session's weeks they've reached
    timetable(user, today)         this week, today, and the next thing to do
    past_weeks(user, today)        the weeks they can go back to
    week_rows(user, term, week)    one reached week's entries, with ticks
    done_for(users, entries)       {user id: done entry ids}, for many users
    content_key(entry)             what the gate matches an address against

Done follows each tool's own record — an EchoSpell card opened
(GroupStepsSeen), an activity passed (or, recorded, sent), a group earned
(GroupProgress), a module day earned (DayProgress), a dialogue practised, a chapter finished,
a test sat, a lesson's every tab opened — and for tools that keep none (a
recital, a library item, Daily Practice), being opened from the scheme
(SchemeOpened). Everything is gathered in a fixed number of queries.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .calendar import break_after_week, terms_for, week_of, week_starts, weeks_in
from .models import DAY_CHOICES, DAY_ORDER, SchemeEntry, SchemeOpened

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
DAY_LABELS = dict(DAY_CHOICES)


def on_scheme(user):
    return bool(
        getattr(user, "is_authenticated", False) and user.is_active and not user.is_staff
        and user.role == "student" and user.school_id and user.level
    )


def _entries(**filters):
    """Live entries only: a draft from the scheme builder is never seen by
    students or teachers until it's published."""
    return (
        SchemeEntry.objects.filter(is_draft=False, **filters)
        .select_related(
            "group__level", "category", "activity__group__level",
            "module_day__week__term__module", "dialogue__level", "sound",
            "chapter__term__book", "recital__section", "library_item", "assessment",
        )
    )


# ---------------------------------------------------------------------------
# Where a student has got to
# ---------------------------------------------------------------------------

def reached(user, today=None):
    """This school year's terms as far as the student has reached them:
    [{"dated", "number", "upto", "current"}] where weeks 1..upto are open.
    The term that's on (or in its mid-term break) is "current". A finished
    term is open to its last week; a term not started isn't listed."""
    today = today or timezone.localdate()
    terms = [t for t in terms_for(user.school) if t.starts <= today]
    if not terms:
        return []
    session = terms[-1].term.session_id
    found = []
    for dated in terms:
        if dated.term.session_id != session:
            continue
        if today > dated.ends:
            upto, current = weeks_in(dated), False
        elif dated.break_starts and dated.break_starts <= today <= dated.break_ends:
            upto, current = week_of(dated, dated.break_starts - timedelta(days=1)), True
        else:
            upto, current = week_of(dated, today), True
        found.append({"dated": dated, "number": dated.number, "upto": upto, "current": current})
    return found


def _reached_filter(user, today=None):
    """(Q for every reached week's entries for the student's level, reached)."""
    from django.db.models import Q

    found = reached(user, today)
    condition = Q(pk__in=[])
    for term in found:
        condition |= Q(term=term["number"], week__lte=term["upto"])
    return Q(level=user.level) & condition, found


# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

def done_for(users, entries):
    """{user id: set of done entry ids}. One query per kind present."""
    from apps.assessments.models import Attempt
    from apps.conversational_dialogue.models import DialogueProgress
    from apps.echospell.models import GroupProgress
    from apps.learning_modules.models import DayProgress
    from apps.reading_club.models import ChapterProgress

    ids = [u.pk for u in users]
    done = {pk: set() for pk in ids}
    by_kind = {}
    for entry in entries:
        by_kind.setdefault(entry.kind, []).append(entry)
    K = SchemeEntry.Kind

    def mark(kind, field, rows):
        """rows: (user, content id) pairs that are done."""
        have = set(rows)
        for entry in by_kind.get(kind, []):
            content_id = getattr(entry, f"{field}_id")
            for pk in ids:
                if (pk, content_id) in have:
                    done[pk].add(entry.pk)

    def ids_of(kind, field):
        return [getattr(e, f"{field}_id") for e in by_kind.get(kind, [])]

    if K.CARD in by_kind:
        from apps.echospell.models import GroupStepsSeen

        cards = by_kind[K.CARD]
        seen = {(user, group): set(ids or []) for user, group, ids in GroupStepsSeen.objects.filter(
            user__in=ids, group__in={e.group_id for e in cards}).values_list("user", "group", "cards_seen")}
        for entry in cards:
            for pk in ids:
                if entry.category_id in seen.get((pk, entry.group_id), ()):
                    done[pk].add(entry.pk)
    if K.ACTIVITY in by_kind:
        from apps.echospell.models import ActivityAttempt

        activities = {e.activity_id: e.activity for e in by_kind[K.ACTIVITY]}
        passed = set()
        for user, activity, status, ok in ActivityAttempt.objects.filter(
                user__in=ids, activity__in=list(activities)).values_list("user", "activity", "status", "passed"):
            # Passed, or for a recorded activity sent: the guided lesson's rule.
            if (ok and status != "awaiting") or (status == "awaiting" and activities[activity].mode == "record"):
                passed.add((user, activity))
        mark(K.ACTIVITY, "activity", passed)
    if K.GROUP in by_kind:
        mark(K.GROUP, "group", GroupProgress.objects.filter(user__in=ids, group__in=ids_of(K.GROUP, "group"))
             .values_list("user", "group"))
    if K.MODULE_DAY in by_kind:
        mark(K.MODULE_DAY, "module_day", DayProgress.objects.filter(
            user__in=ids, day__in=ids_of(K.MODULE_DAY, "module_day")).values_list("user", "day"))
    if K.DIALOGUE in by_kind:
        mark(K.DIALOGUE, "dialogue", DialogueProgress.objects.filter(
            user__in=ids, dialogue__in=ids_of(K.DIALOGUE, "dialogue")).values_list("user", "dialogue"))
    if K.CHAPTER in by_kind:
        mark(K.CHAPTER, "chapter", ChapterProgress.objects.filter(
            user__in=ids, chapter__in=ids_of(K.CHAPTER, "chapter")).values_list("user", "chapter"))
    if K.ASSESSMENT in by_kind:
        mark(K.ASSESSMENT, "assessment", Attempt.objects.filter(
            user__in=ids, assessment__in=ids_of(K.ASSESSMENT, "assessment"))
            .exclude(status=Attempt.Status.IN_PROGRESS).values_list("user", "assessment"))
    sounds = by_kind.get(K.SOUND, []) + by_kind.get(K.TRICK, [])
    if sounds:
        from apps.tricks.models import LessonProgress
        from apps.tricks.progress import _tabs_with_content

        lessons = list({e.sound for e in sounds if e.sound})
        needed = _tabs_with_content(lessons)
        finished = {
            (user, lesson) for user, lesson, seen in
            LessonProgress.objects.filter(user__in=ids, lesson__in=lessons).values_list("user", "lesson", "tabs_seen")
            if set(needed.get(lesson, [])) <= set(seen or [])
        }
        for kind in (K.SOUND, K.TRICK):
            mark(kind, "sound", finished)
    # Everything else: opened from the scheme.
    others = [e.pk for kind, found in by_kind.items()
              if kind in (K.RECITAL, K.LIBRARY, K.DAILY_PRACTICE) for e in found]
    if others:
        for user, entry in SchemeOpened.objects.filter(user__in=ids, entry__in=others).values_list("user", "entry"):
            done[user].add(entry)
    return done


# ---------------------------------------------------------------------------
# What the student sees
# ---------------------------------------------------------------------------

def _row(entry, done_ids, today_name=""):
    return {
        "entry": entry, "title": entry.title, "kind": entry.get_kind_display(),
        "done": entry.pk in done_ids,
        "day": entry.day, "day_label": DAY_LABELS.get(entry.day) or "Any day",
        "is_today": bool(today_name) and entry.day in ("", today_name),
        "url": reverse("scheme:go", args=[entry.pk]),
    }


def _sorted(entries):
    return sorted(entries, key=lambda e: (DAY_ORDER.index(e.day) if e.day in DAY_ORDER else 0, e.order, e.pk))


def timetable(user, today=None):
    """This week for a student: {"state", "place", "term", "week", "today",
    "rows", "today_rows", "next", "done", "total", "has_scheme"}.

    state: "week" (a school week, possibly the weekend), "break", "holiday",
    "no_term" (no calendar yet) or "empty" (no scheme this term)."""
    today = today or timezone.localdate()
    found = reached(user, today)
    current = next((t for t in found if t["current"]), None)
    base = {"state": "no_term", "term": None, "week": None, "rows": [], "today_rows": [],
            "next": None, "done": 0, "total": 0, "today_name": "", "has_scheme": False}
    if current is None:
        base["state"] = "holiday" if found else "no_term"
        base["has_scheme"] = bool(found) and _entries(level=user.level).exists()
        return base
    dated = current["dated"]
    base.update(term=dated, has_scheme=_entries(level=user.level, term=dated.number).exists())
    if not base["has_scheme"]:
        base["state"] = "empty"
        return base
    if dated.break_starts and dated.break_starts <= today <= dated.break_ends:
        base["state"] = "break"
        return base

    week = current["upto"]
    weekday = today.weekday()
    today_name = WEEKDAYS[weekday] if weekday < 5 else ""
    entries = _sorted(_entries(level=user.level, term=dated.number, week=week))
    done_ids = done_for([user], entries)[user.pk]
    rows = [_row(e, done_ids, today_name) for e in entries]
    today_rows = [r for r in rows if r["is_today"]]
    # Next: today's first not done, then the week's first not done.
    nxt = next((r for r in today_rows if not r["done"]), None) or next((r for r in rows if not r["done"]), None)
    base.update(state="week", week=week, rows=rows, today_rows=today_rows, next=nxt,
                done=sum(1 for r in rows if r["done"]), total=len(rows), today_name=today_name,
                today_label=DAY_LABELS.get(today_name, "Weekend"))
    return base


def past_weeks(user, today=None):
    """The weeks a student can go back to, newest first, with how much of
    each is done: [{"term", "week", "label", "done", "total", "is_current"}]
    — the same shape as path.path()'s weeks, so one page shows either."""
    condition, found = _reached_filter(user, today)
    entries = list(_entries().filter(condition))
    done_ids = done_for([user], entries)[user.pk]
    weeks = {}
    for entry in entries:
        key = (entry.term, entry.week)
        weeks.setdefault(key, {"done": 0, "total": 0})
        weeks[key]["total"] += 1
        weeks[key]["done"] += entry.pk in done_ids
    current = {(t["number"], t["upto"]) for t in found if t["current"]}
    names = {t["number"]: t["dated"] for t in found}
    return [
        {"term": term, "week": week, "label": f"{names[term].term.get_number_display()}, Week {week}",
         "is_current": (term, week) in current, **counts}
        for (term, week), counts in sorted(weeks.items(), reverse=True)
    ]


def week_rows(user, term, week, today=None):
    """One reached week's entries with ticks, or None if not reached."""
    found = reached(user, today)
    if not any(t["number"] == term and week <= t["upto"] for t in found):
        return None
    entries = _sorted(_entries(level=user.level, term=term, week=week))
    done_ids = done_for([user], entries)[user.pk]
    return [_row(e, done_ids) for e in entries]


# ---------------------------------------------------------------------------
# What may be opened
# ---------------------------------------------------------------------------

def content_key(entry):
    """The address-shaped key of an entry's content, as gate.py reads it
    from a URL's arguments."""
    K, c = SchemeEntry.Kind, entry.content
    if entry.kind == K.DAILY_PRACTICE:
        return ("daily_practice",)
    if c is None:
        return None
    if entry.kind in (K.GROUP, K.CARD):
        return ("group", c.level.slug, c.slug)
    if entry.kind == K.ACTIVITY:
        return ("group", c.group.level.slug, c.group.slug)
    if entry.kind == K.MODULE_DAY:
        week, term = c.week, c.week.term
        return ("module_day", term.module.slug, term.slug, week.slug, c.day_name)
    if entry.kind == K.DIALOGUE:
        return ("dialogue", c.level.slug, c.slug)
    if entry.kind in (K.SOUND, K.TRICK):
        return (entry.kind, c.slug)
    if entry.kind == K.CHAPTER:
        return ("chapter", c.term.book.slug, c.term.slug, c.slug)
    if entry.kind == K.RECITAL:
        return ("recital", c.section.slug, c.slug)
    if entry.kind == K.LIBRARY:
        return ("library", c.slug)
    if entry.kind == K.ASSESSMENT:
        return ("assessment", c.slug)
    return None


def open_keys(user, today=None):
    """Every content key in the weeks the student has reached."""
    condition, _found = _reached_filter(user, today)
    return {key for key in (content_key(e) for e in _entries().filter(condition)) if key}


def content_url(entry):
    """Where an entry's content lives."""
    K, c = SchemeEntry.Kind, entry.content
    if entry.kind == K.DAILY_PRACTICE:
        return reverse("daily_practice:home")
    if entry.kind == K.CARD:
        return reverse("echospell:card_detail", args=[c.level.slug, c.slug, entry.category.slug])
    if entry.kind == K.ACTIVITY:
        return reverse("echospell:activity_detail", args=[c.group.level.slug, c.group.slug, c.slug])
    if entry.kind == K.GROUP:
        return reverse("echospell:group_detail", args=[c.level.slug, c.slug])
    if entry.kind == K.MODULE_DAY:
        week, term = c.week, c.week.term
        return reverse("learning_modules:day_detail", args=[term.module.slug, term.slug, week.slug, c.day_name])
    if entry.kind == K.DIALOGUE:
        return reverse("conversational_dialogue:dialogue", args=[c.level.slug, c.slug])
    if entry.kind == K.SOUND:
        return reverse("book:sound_detail", args=[c.slug])
    if entry.kind == K.TRICK:
        return reverse("tricks:lesson", args=[c.slug])
    if entry.kind == K.CHAPTER:
        return reverse("reading_club:chapter_detail", args=[c.term.book.slug, c.term.slug, c.slug])
    if entry.kind == K.RECITAL:
        return reverse("assembly_recitals:recital", args=[c.section.slug, c.slug])
    if entry.kind == K.LIBRARY:
        return reverse("diction_library:detail", args=[c.slug])
    return reverse("assessments:detail", args=[c.slug])


def class_week(teacher, level, pupils, today=None):
    """This week of `level`'s scheme for a teacher's class: the entries by
    day, and how many each pupil has done. {"label", "rows", "total",
    "done": {pupil id: n}} — or no rows outside a school week."""
    today = today or timezone.localdate()
    current = next((t for t in reached(teacher, today) if t["current"]), None)
    result = {"label": "", "rows": [], "total": 0, "done": {}}
    if current is None or not level:
        return result
    dated, week = current["dated"], current["upto"]
    on_break = bool(dated.break_starts and dated.break_starts <= today <= dated.break_ends)
    result["label"] = (f"{dated.term.get_number_display()}: mid-term break" if on_break
                       else f"{dated.term.get_number_display()}, Week {week}")
    if on_break:
        return result
    entries = _sorted(_entries(level=level, term=dated.number, week=week))
    done = done_for(pupils, entries)
    weekday = today.weekday()
    today_name = WEEKDAYS[weekday] if weekday < 5 else ""
    result.update(
        rows=[{**_row(e, set(), today_name), "url": content_url(e)} for e in entries],
        total=len(entries),
        done={pk: len(ids) for pk, ids in done.items()},
    )
    return result


# ---------------------------------------------------------------------------
# A teacher's plan: the whole term, to prepare ahead
# ---------------------------------------------------------------------------

def _next_school_day(dated_terms, today):
    """The next teaching day after today: (term, date), skipping weekends,
    the mid-term break and holidays — or (None, None)."""
    day = today + timedelta(days=1)
    for _ in range(200):
        if day.weekday() < 5:
            for dated in dated_terms:
                in_break = dated.break_starts and dated.break_starts <= day <= dated.break_ends
                if dated.starts <= day <= dated.ends and not in_break:
                    return dated, day
        day += timedelta(days=1)
    return None, None


def term_plan(teacher, level, number, pupils, today=None):
    """The whole of one term of `level`'s scheme for a teacher, to prepare:
    {"dated", "weeks": [...], "next_day": {...}, "pupils": n}. Each week has
    its dates, its state ("taught", "now", "coming"), and its days Monday to
    Friday (plus "any day"), each lesson with how many pupils have done it
    (up to this week). A fixed number of queries, however big the class."""
    today = today or timezone.localdate()
    terms = terms_for(teacher.school)
    newest = terms[-1].term.session_id if terms else None
    year = [t for t in terms if t.term.session_id == newest]
    dated = next((t for t in year if t.number == number), None)
    entries = _sorted(_entries(level=level, term=number))
    reach = {t["number"]: t for t in reached(teacher, today)}.get(number)
    upto = reach["upto"] if reach else 0
    shown = [e for e in entries if e.week <= upto]
    done = done_for(pupils, shown) if pupils else {}
    counts = {}
    for ids in done.values():
        for pk in ids:
            counts[pk] = counts.get(pk, 0) + 1

    firsts = dict(week_starts(dated)) if dated else {}
    # Every teaching week of the term, and any week the scheme goes beyond it.
    spans = [e.week for e in entries] + ([weeks_in(dated)] if dated else [])
    last = max(spans or [12])
    break_after = break_after_week(dated) if dated else 0
    current = reach["upto"] if reach and reach["current"] else None

    by_week = {}
    for entry in entries:
        by_week.setdefault(entry.week, []).append(entry)
    weeks = []
    for number_ in range(1, last + 1):
        monday = firsts.get(number_)
        days = []
        for key, label in DAY_CHOICES:
            rows = [e for e in by_week.get(number_, []) if e.day == key]
            if not rows:
                continue
            on = monday + timedelta(days=WEEKDAYS.index(key)) if monday and key in WEEKDAYS else None
            days.append({
                "key": key, "label": label if key else "Any day this week", "date": on, "is_today": on == today,
                "rows": [{"entry": e, "title": e.title, "kind": e.get_kind_display(), "url": content_url(e),
                          "done": counts.get(e.pk, 0) if number_ <= upto else None} for e in rows],
            })
        weeks.append({
            "number": number_, "monday": monday, "friday": monday + timedelta(days=4) if monday else None,
            "state": "now" if number_ == current else "taught" if number_ <= upto else "coming",
            "days": days, "break_after": break_after and number_ == break_after,
        })

    next_day = prepare_for(teacher, level, today, year)
    return {"dated": dated, "weeks": weeks, "next_day": next_day, "pupils": len(pupils), "current": current}


def prepare_for(teacher, level, today=None, year=None):
    """What the class has on the next school day, for a teacher to prepare:
    {"date", "term", "week", "rows"}, or None outside a school year."""
    today = today or timezone.localdate()
    if year is None:
        terms = terms_for(teacher.school)
        newest = terms[-1].term.session_id if terms else None
        year = [t for t in terms if t.term.session_id == newest]
    term_of_day, day = _next_school_day(year, today)
    if term_of_day is None or not level:
        return None
    week = week_of(term_of_day, day)
    name = WEEKDAYS[day.weekday()]
    rows = [e for e in _sorted(_entries(level=level, term=term_of_day.number, week=week)) if e.day in ("", name)]
    return {"date": day, "term": term_of_day, "week": week,
            "rows": [{"title": e.title, "kind": e.get_kind_display(), "url": content_url(e), "any_day": not e.day}
                     for e in rows]}
