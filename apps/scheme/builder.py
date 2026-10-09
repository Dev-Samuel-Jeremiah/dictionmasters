"""
The scheme builders: a level's scheme of work, planned from the content
already on the site, saved as a draft to check, edit and publish in the
control room's Scheme of work.

The scheme holds four courses, and two builders share it, each looking
after its own part and leaving the other's alone:

    book_plan(level, terms)     EchoSpell, the book (BOOK_KINDS), no AI:
                                Group N is Week N, its cards one a day,
                                its activities on Friday
    build(level, terms, note)   Learning Modules (a day every school day),
                                the 44 Academy and Tricks to Sound Fluent
                                (a sound and a trick a week, side by side)
                                (AI_KINDS), fitted around the book's days
    catalogue(level, terms)     what build can place, in each course's order

Every other course and tool (Assembly Recitals, Reading Club, Daily
Practice, …) is open to students from the sidebar, not scheduled. A build
replaces everything in the draft but the other builder's part, so old
entries of those kinds go with it. With no draft yet, a build starts from
the live scheme, so building one part keeps the other part as published.

The plan comes from OpenAI when a key is set (OPENAI_API_KEY, the model in
OPENAI_MODEL — the same as the rest of the site), told to plan the way a
curriculum planner would (RULES). Its answer is checked line by line: only
content in the catalogue, of the right kind, on a real week and day of a
term asked for, is kept. With no key, or if the AI fails or gives back
nothing usable, a careful plan from the same rules is made here instead
(rule_plan), so the button always works.

A build only ever writes drafts; students see nothing until it's published.
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q

from apps.accounts.access import limit_to_level_list

from .models import SchemeEntry

logger = logging.getLogger("apps.scheme.builder")

API_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SECONDS = 90
MAX_PER_KIND = 150
MAX_NOTE = 1000
MAX_PER_DAY = 3
DAYS = ["any", "monday", "tuesday", "wednesday", "thursday", "friday"]
WEEKDAYS = DAYS[1:]
K = SchemeEntry.Kind
BOOK_KINDS = {K.CARD, K.ACTIVITY, K.GROUP}           # Build from the book
AI_KINDS = {K.MODULE_DAY, K.SOUND, K.TRICK}           # Build with AI

RULES = """You plan part of a school scheme of work for British English pronunciation for
Nigerian school children: three courses, Learning Modules, the 44 Academy (the 44 sounds)
and Tricks to Sound Fluent. You get one level's terms (how many teaching weeks each has,
and the week its mid-term break follows), a catalogue of those courses' content, each
listed in its own teaching order, and how many EchoSpell lessons (the book, placed
already and not yours to place) each day holds. Place your courses' content on weeks and days.

Plan like an experienced curriculum planner:
- Learning Modules days are a daily course: exactly one every school day (Monday to
  Friday), in order, even on a day the EchoSpell lessons fill.
- The 44 Academy and Tricks to Sound Fluent run side by side from week 1: one sound and
  one trick each week (sounds on Tuesday, tricks on Thursday, or the lightest day).
- Keep each course in its catalogue order; never put a later item before an earlier one.
- Besides the Learning Modules day, at most 3 lessons a day, counting the EchoSpell
  lessons already there: put the sounds and tricks on the lighter days.
- The week before the last week of a term is revision: lighter, revisiting earlier content.
- Use "any" as the day for an item that can be done on any day that week.
- Only use ids from the catalogue.
Return every placement."""


# ---------------------------------------------------------------------------
# What there is to teach
# ---------------------------------------------------------------------------

def catalogue(level, terms):
    """{kind: [{"id": "kind:pk", "title"}]} of the AI builder's courses
    (AI_KINDS), each in its own order."""
    from apps.book.models import ACADEMY, TRICKS
    from apps.learning_modules.models import Day
    from apps.tricks.progress import lessons_in_order

    found = {
        K.MODULE_DAY: [
            {"id": f"module_day:{d.pk}", "title": f"{d.week.term.module.name}, {d.week.term.name}, {d.week.display_name}, {d.get_day_name_display()}"}
            for d in limit_to_level_list(
                Day.objects.filter(is_published=True, week__term__module__is_published=True),
                _as_level(level), field="week__term__module__levels",
            ).select_related("week__term__module").order_by(
                "week__term__module__order", "week__term__module__name", "week__term__order", "week__term__id",
                "week__number", "order")
        ],
        K.SOUND: [{"id": f"sound:{s.pk}", "title": s.name} for s in lessons_in_order(ACADEMY)],
        K.TRICK: [{"id": f"trick:{s.pk}", "title": s.name} for s in lessons_in_order(TRICKS)],
    }
    return {kind: items[:MAX_PER_KIND] for kind, items in found.items() if items}


class _as_level:
    """Just enough of a student to ask access.py what one level may see."""

    is_authenticated = True
    is_staff = False
    role = "student"
    additional_levels = ""

    def __init__(self, level):
        self.level = level
        self.all_levels = [level]


# ---------------------------------------------------------------------------
# Checking a plan
# ---------------------------------------------------------------------------

def clean_plan(placements, items, terms, taken=None):
    """Keep only placements that are real: a catalogue id, a term asked for,
    a week inside it, a real day; no duplicates; at most MAX_PER_DAY a day,
    counting what's `taken` already ({(term, week, day): n}, the book's
    lessons) — besides the day's Learning Modules day, the daily course,
    which is never squeezed out. [(term, week, day, id)]."""
    weeks = {t["number"]: t["weeks"] for t in terms}
    known = {item["id"] for found in items.values() for item in found}
    kept, seen, per_day = [], set(), dict(taken or {})
    for p in placements:
        try:
            term, week, day, item = int(p["term"]), int(p["week"]), str(p["day"]).lower(), str(p["item"])
        except (KeyError, TypeError, ValueError):
            continue
        day = "" if day == "any" else day
        if term not in weeks or not 1 <= week <= weeks[term] or (day and day not in WEEKDAYS) or item not in known:
            continue
        key = (term, week, day, item)
        daily = item.startswith(f"{K.MODULE_DAY}:")
        if key in seen or (not daily and per_day.get((term, week, day), 0) >= MAX_PER_DAY):
            continue
        seen.add(key)
        if not daily:
            per_day[(term, week, day)] = per_day.get((term, week, day), 0) + 1
        kept.append(key)
    return kept


# ---------------------------------------------------------------------------
# Planning: by AI, or by rule
# ---------------------------------------------------------------------------

class PlanError(Exception):
    pass


def _schema():
    return {
        "type": "object", "additionalProperties": False, "required": ["entries"],
        "properties": {"entries": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["term", "week", "day", "item"],
            "properties": {"term": {"type": "integer"}, "week": {"type": "integer"},
                           "day": {"type": "string", "enum": DAYS}, "item": {"type": "string"}},
        }}},
    }


def ai_plan(level, terms, items, note="", taken=None):
    """Placements from OpenAI, or PlanError."""
    if not getattr(settings, "OPENAI_API_KEY", ""):
        raise PlanError("No OpenAI key is set.")
    request_body = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": RULES},
            {"role": "user", "content": json.dumps({
                "level": level,
                "terms": [{"term": t["number"], "teaching_weeks": t["weeks"], "break_after_week": t["break_after"]}
                          for t in terms],
                "catalogue": {kind: found for kind, found in items.items()},
                "echospell_lessons_per_day": [{"term": t, "week": w, "day": d or "any", "lessons": n}
                                              for (t, w, d), n in sorted((taken or {}).items())],
                "planner_note": note[:MAX_NOTE],
            })},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "scheme_of_work", "strict": True,
                                                                    "schema": _schema()}},
    }
    request = urllib.request.Request(
        API_URL, data=json.dumps(request_body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)["entries"]
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as error:
        raise PlanError(f"The AI planner didn't answer usefully: {error}") from error


# A sound and a trick each week, side by side from week 1.
WEEKLY = [("tuesday", K.SOUND), ("thursday", K.TRICK)]


def rule_plan(terms, items, taken=None):
    """A careful plan from the same rules, with no AI: placements as dicts,
    fitted around what's `taken` already. Courses run on in order from one
    term to the next."""
    queues = {kind: [i["id"] for i in found] for kind, found in items.items()}
    load = dict(taken or {})
    plan = []

    def put(term, week, day, kind=None, item=None):
        """Place the next of `kind` (or `item`) if the day has room. A
        Learning Modules day always has room: it's the daily course."""
        daily = kind == K.MODULE_DAY or (item or "").startswith(f"{K.MODULE_DAY}:")
        if not daily and load.get((term, week, day), 0) >= MAX_PER_DAY:
            return False
        item = item or (queues[kind].pop(0) if queues.get(kind) else None)
        if not item:
            return False
        plan.append({"term": term, "week": week, "day": day, "item": item})
        if not daily:
            load[(term, week, day)] = load.get((term, week, day), 0) + 1
        return True

    for term in terms:
        n, last = term["number"], term["weeks"]
        revision = last - 1 if last >= 4 else 0
        for week in range(1, last + 1):
            if week == revision:
                # Revision: no new course content; a day each on lessons from
                # earlier in the term, spread across it.
                earlier = list(dict.fromkeys(p["item"] for p in plan if p["term"] == n))
                step = max(1, len(earlier) // 5)
                for day, item in zip(WEEKDAYS, earlier[::step]):
                    put(n, week, day, item=item)
                continue
            for day in WEEKDAYS:
                put(n, week, day, K.MODULE_DAY)
            for day, kind in WEEKLY:
                if not queues.get(kind):                    # one course done: two of the other
                    kind = K.TRICK if kind == K.SOUND else K.SOUND
                # Its own day, or the lightest day with room.
                for choice in [day] + sorted(WEEKDAYS, key=lambda d: load.get((n, week, d), 0)):
                    if put(n, week, choice, kind):
                        break
    return plan


# ---------------------------------------------------------------------------
# From the book: EchoSpell's groups are the weeks
# ---------------------------------------------------------------------------

BOOK_DAYS = ["monday", "tuesday", "wednesday", "thursday"]      # Friday is for the activities


def book_plan(level, terms):
    """The scheme the way the book is laid out: the level's EchoSpell
    Group 1 is Week 1, Group 2 Week 2, … running on through the terms'
    weeks. A week holds its group's cards that have something in them, one
    a day Monday to Thursday in the level's card order (two a day when
    there are more than four), and the group's activities on Friday.
    [(term, week, day, item)]."""
    from apps.echospell.lesson_path import _cards_with_content
    from apps.echospell.models import Activity, Group, Level

    found = Level.objects.filter(name=level).first()
    if found is None:
        return []
    groups = list(Group.objects.filter(level=found).order_by("number"))
    activities = {}
    for activity in (Activity.objects.filter(group__in=groups, is_published=True)
                     .annotate(item_count=Count("items")).filter(item_count__gt=0).order_by("order", "id")):
        activities.setdefault(activity.group_id, []).append(activity)
    weeks = [(term["number"], week) for term in terms for week in range(1, term["weeks"] + 1)]
    plan = []
    for (term, week), group in zip(weeks, groups):
        cards = _cards_with_content(found, group)
        for i, category in enumerate(cards):
            day = BOOK_DAYS[i * len(BOOK_DAYS) // len(cards)] if len(cards) > len(BOOK_DAYS) else BOOK_DAYS[i]
            plan.append((term, week, day, f"card:{group.pk}-{category.pk}"))
        for activity in activities.get(group.pk, []):
            plan.append((term, week, "friday", f"activity:{activity.pk}"))
    return plan


def build_from_book(level, terms):
    """book_plan saved as the level's draft, keeping the AI builder's part.
    {"count", "groups", "weeks"}."""
    plan = book_plan(level, terms)
    count = save_draft(level, terms, plan, keep=AI_KINDS)
    weeks_filled = {(term, week) for term, week, _day, _item in plan}      # one group per week
    return {"count": count, "groups": len(weeks_filled), "weeks": sum(t["weeks"] for t in terms)}


# ---------------------------------------------------------------------------
# Building the draft
# ---------------------------------------------------------------------------

def _drafted(level, numbers):
    """The terms that have a draft already."""
    return set(SchemeEntry.objects.filter(level=level, term__in=numbers, is_draft=True)
               .values_list("term", flat=True))


def taken_days(level, terms, keep):
    """{(term, week, day): n} of the `keep` kinds a build must fit around:
    in the draft, or in the live scheme for a term with no draft yet."""
    numbers = [t["number"] for t in terms]
    drafted = _drafted(level, numbers)
    rows = (SchemeEntry.objects.filter(level=level, kind__in=keep)
            .filter(Q(is_draft=True, term__in=drafted) | Q(is_draft=False, term__in=set(numbers) - drafted))
            .values("term", "week", "day").annotate(n=Count("id")))
    return {(r["term"], r["week"], r["day"]): r["n"] for r in rows}


@transaction.atomic
def save_draft(level, terms, placements, keep=()):
    """Replace the level's draft for these terms with `placements`, keeping
    its entries of the `keep` kinds (the other builder's part). A term with
    no draft yet starts from its live scheme's `keep` entries."""
    numbers = [t["number"] for t in terms]
    fresh = set(numbers) - _drafted(level, numbers)
    copies = list(SchemeEntry.objects.filter(level=level, term__in=fresh, is_draft=False, kind__in=keep))
    for entry in copies:
        entry.pk, entry.is_draft = None, True
    SchemeEntry.objects.bulk_create(copies)
    SchemeEntry.objects.filter(level=level, term__in=numbers, is_draft=True).exclude(kind__in=keep).delete()
    # New entries go after the kept ones on their day.
    orders = {(r["term"], r["week"], r["day"]): r["top"]
              for r in SchemeEntry.objects.filter(level=level, term__in=numbers, is_draft=True)
              .values("term", "week", "day").annotate(top=Max("order"))}
    new = []
    for term, week, day, item in placements:
        kind, _sep, pk = item.partition(":")
        field = SchemeEntry.FIELD_FOR.get(kind)
        orders[(term, week, day)] = order = (orders.get((term, week, day)) or 0) + 1
        entry = SchemeEntry(level=level, term=term, week=week, day=day, kind=kind, order=order, is_draft=True)
        if kind == SchemeEntry.Kind.CARD:
            # "card:<group>-<card type>"
            group_id, _dash, category_id = pk.partition("-")
            entry.group_id, entry.category_id = int(group_id), int(category_id)
        elif field:
            setattr(entry, f"{field}_id", int(pk))
        new.append(entry)
    SchemeEntry.objects.bulk_create(new)
    return len(new)


def build(level, terms, note="", use_ai=True):
    """Plan Learning Modules, the 44 Academy and Tricks for `terms`
    ([{"number", "weeks", "break_after"}]) around the book's days, and save
    them as `level`'s draft, keeping the book's part.
    {"count", "source": "ai" | "rules", "message"}."""
    items = catalogue(level, terms)
    if not items:
        return {"count": 0, "source": "", "message": f"There's no content for {level} to plan with yet."}
    taken = taken_days(level, terms, BOOK_KINDS)
    source, message, placements = "rules", "", []
    if use_ai:
        try:
            placements = clean_plan(ai_plan(level, terms, items, note, taken), items, terms, taken)
            source = "ai"
            if not placements:
                message = "The AI planner's answer had nothing usable, so the plan was made by rule."
        except PlanError as error:
            logger.warning("Scheme builder for %s: %s", level, error)
            message = ("No OpenAI key is set, so the plan was made by rule."
                       if "No OpenAI key" in str(error) else "The AI planner didn't answer, so the plan was made by rule.")
    if not placements:
        source = "rules"
        placements = clean_plan(rule_plan(terms, items, taken), items, terms, taken)
    count = save_draft(level, terms, placements, keep=BOOK_KINDS)
    return {"count": count, "source": source, "message": message}
