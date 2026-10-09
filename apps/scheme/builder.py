"""
The scheme builder: a whole term (or year) of the scheme of work for one
level, planned from the content already on the site, saved as a draft to
check, edit and publish in the control room's Scheme of work.

    catalogue(level, terms)     everything the level can be taught, by kind,
                                in each course's own order
    book_plan(level, terms)     the book's layout, no AI: Group N is Week N,
                                its cards one a day, its activities on Friday
    build(level, terms, note)   plan it and save it as the level's draft

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
from django.db.models import Count

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

RULES = """You plan a school scheme of work for British English pronunciation for Nigerian
school children. You get one level's terms (how many teaching weeks each has, and the
week its mid-term break follows) and a catalogue of the content that level can be taught,
each course listed in its own teaching order. Place content on weeks and days.

Plan like an experienced curriculum planner:
- Every school day (Monday to Friday) of every week has at least one item; at most 3 a day.
- Keep each course in its catalogue order; never put a later item before an earlier one.
- Spread courses across the week for variety rather than one course all week.
- Learning Modules days are a daily course: one a school day, in order.
- EchoSpell groups: about one a week. 44 Academy sounds come before Tricks to Sound Fluent.
- Conversational Dialogues have the term and week they were written for: use those.
- Daily Practice ("daily_practice:") on Fridays.
- CA 1 around week 4 or 5, CA 2 around week 8 or 9, the exam in the last week;
  the week before the exam is revision: lighter, revisiting earlier content.
- Use "any" as the day for an item that can be done on any day that week.
- Only use ids from the catalogue, and an assessment only in the term it's for.
Return every placement."""


# ---------------------------------------------------------------------------
# What there is to teach
# ---------------------------------------------------------------------------

def catalogue(level, terms):
    """{kind: [{"id": "kind:pk", "title", ...}]} in each course's own order."""
    from apps.assembly_recitals.models import Recital
    from apps.assessments.models import Assessment
    from apps.book.models import ACADEMY, TRICKS
    from apps.conversational_dialogue.models import Dialogue
    from apps.diction_library.models import LibraryItem
    from apps.echospell.models import Group
    from apps.learning_modules.models import Day
    from apps.reading_club.models import Chapter
    from apps.tricks.progress import lessons_in_order

    numbers = [t["number"] for t in terms]
    found = {
        K.GROUP: [{"id": f"group:{g.pk}", "title": f"EchoSpell Group {g.number}{': ' + g.title if g.title else ''}"}
                  for g in Group.objects.filter(level__name=level, level__is_published=True).order_by("number")],
        K.MODULE_DAY: [
            {"id": f"module_day:{d.pk}", "title": f"{d.week.term.module.name}, {d.week.term.name}, {d.week.display_name}, {d.get_day_name_display()}"}
            for d in limit_to_level_list(
                Day.objects.filter(is_published=True, week__term__module__is_published=True),
                _as_level(level), field="week__term__module__levels",
            ).select_related("week__term__module").order_by(
                "week__term__module__order", "week__term__module__name", "week__term__order", "week__term__id",
                "week__number", "order")
        ],
        K.DIALOGUE: [{"id": f"dialogue:{d.pk}", "title": d.title, "term": d.term, "week": d.week, "day": d.day}
                     for d in Dialogue.objects.filter(level__name=level, is_published=True, term__in=numbers)],
        K.SOUND: [{"id": f"sound:{s.pk}", "title": s.name} for s in lessons_in_order(ACADEMY)],
        K.TRICK: [{"id": f"trick:{s.pk}", "title": s.name} for s in lessons_in_order(TRICKS)],
        K.CHAPTER: [{"id": f"chapter:{c.pk}", "title": f"{c.term.book.title}: {c.title}"}
                    for c in limit_to_level_list(Chapter.objects.filter(is_published=True), _as_level(level),
                                                 field="term__book__levels")
                    .select_related("term__book").order_by("term__book__order", "term__order", "number")],
        K.RECITAL: [{"id": f"recital:{r.pk}", "title": f"{r.section.name}: {r.title}"}
                    for r in Recital.objects.filter(is_published=True).select_related("section").order_by("section__order", "order")],
        K.LIBRARY: [{"id": f"library:{i.pk}", "title": i.title}
                    for i in limit_to_level_list(LibraryItem.objects.filter(is_published=True, school__isnull=True),
                                                 _as_level(level)).order_by("order", "title")],
        K.ASSESSMENT: [
            {"id": f"assessment:{a.pk}", "title": a.title, "kind": a.kind, "term": a.term, "ca_number": a.ca_number}
            for a in Assessment.objects.filter(is_published=True, level=level, kind__in=["ca", "exam"], term__in=numbers)
            .order_by("term", "kind", "ca_number")
        ],
        K.DAILY_PRACTICE: [{"id": "daily_practice:", "title": "Daily Practice"}],
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

def clean_plan(placements, items, terms):
    """Keep only placements that are real: a catalogue id, a term asked for,
    a week inside it, a real day; an assessment only in its own term; no
    duplicates; at most MAX_PER_DAY a day. [(term, week, day, id)]."""
    weeks = {t["number"]: t["weeks"] for t in terms}
    known = {item["id"]: item for found in items.values() for item in found}
    kept, seen, per_day = [], set(), {}
    for p in placements:
        try:
            term, week, day, item = int(p["term"]), int(p["week"]), str(p["day"]).lower(), str(p["item"])
        except (KeyError, TypeError, ValueError):
            continue
        day = "" if day == "any" else day
        if term not in weeks or not 1 <= week <= weeks[term] or (day and day not in WEEKDAYS) or item not in known:
            continue
        found = known[item]
        if item.startswith("assessment:") and found.get("term") != term:
            continue
        key = (term, week, day, item)
        if key in seen or per_day.get((term, week, day), 0) >= MAX_PER_DAY:
            continue
        seen.add(key)
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


def ai_plan(level, terms, items, note=""):
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


def rule_plan(terms, items):
    """A careful plan from the same rules, with no AI: placements as dicts.
    Courses run on in order from one term to the next."""
    queues = {kind: [i["id"] for i in found if kind not in (K.ASSESSMENT, K.DIALOGUE, K.DAILY_PRACTICE)]
              for kind, found in items.items()}
    take = lambda kind: queues[kind].pop(0) if queues.get(kind) else None
    plan = []
    put = lambda term, week, day, item: item and plan.append({"term": term, "week": week, "day": day, "item": item})
    # A weekly slot for each course: (day, kind), the sounds before the tricks.
    weekly = [("monday", K.GROUP), ("tuesday", K.SOUND), ("wednesday", K.CHAPTER),
              ("thursday", K.RECITAL), ("any", K.LIBRARY)]
    for term in terms:
        n, last = term["number"], term["weeks"]
        tests = {i.get("kind") + str(i.get("ca_number") or ""): i["id"]
                 for i in items.get(K.ASSESSMENT, []) if i.get("term") == n}
        ca1, ca2 = max(2, round(last * 0.4)), max(3, round(last * 0.75))
        revision = last - 1 if last >= 4 else 0
        for week in range(1, last + 1):
            if week == revision:
                # Revision: no new course content; a day each on lessons from
                # earlier in the term, spread across it.
                earlier = list(dict.fromkeys(
                    p["item"] for p in plan
                    if p["term"] == n and not p["item"].startswith(("assessment:", "daily_practice:"))))
                step = max(1, len(earlier) // 5)
                for day, item in zip(WEEKDAYS, earlier[::step]):
                    put(n, week, day, item)
                if items.get(K.DAILY_PRACTICE):
                    put(n, week, "friday", "daily_practice:")
                continue
            for day in WEEKDAYS:
                put(n, week, day, take(K.MODULE_DAY))
            for day, kind in weekly:
                if kind == K.SOUND and not queues.get(K.SOUND):
                    kind = K.TRICK
                put(n, week, day, take(kind))
            if items.get(K.DAILY_PRACTICE):
                put(n, week, "friday", "daily_practice:")
            if week == ca1:
                put(n, week, "thursday", tests.get("ca1"))
            if week == ca2:
                put(n, week, "thursday", tests.get("ca2"))
            if week == last:
                put(n, week, "wednesday", tests.get("exam"))
        for dialogue in items.get(K.DIALOGUE, []):
            if dialogue.get("term") == n and dialogue.get("week", 99) <= last:
                put(n, dialogue["week"], dialogue.get("day") or "any", dialogue["id"])
    return plan


# ---------------------------------------------------------------------------
# Building the draft
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# From the book: EchoSpell's groups are the weeks
# ---------------------------------------------------------------------------

BOOK_DAYS = ["monday", "tuesday", "wednesday", "thursday"]      # Friday is for the activities


def book_plan(level, terms):
    """The scheme the way the book is laid out: the level's EchoSpell
    Group 1 is Week 1, Group 2 Week 2, … running on through the terms'
    weeks. A week holds its group's cards that have something in them, one
    a day Monday to Thursday in the level's card order (two a day when
    there are more than four), and the group's activities on Friday —
    Daily Practice instead when it has none. [(term, week, day, item)]."""
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
        if not activities.get(group.pk):
            plan.append((term, week, "friday", "daily_practice:"))
    return plan


def build_from_book(level, terms):
    """book_plan saved as the level's draft. {"count", "groups", "weeks"}."""
    plan = book_plan(level, terms)
    count = save_draft(level, terms, plan)
    weeks_filled = {(term, week) for term, week, _day, _item in plan}      # one group per week
    return {"count": count, "groups": len(weeks_filled), "weeks": sum(t["weeks"] for t in terms)}


@transaction.atomic
def save_draft(level, terms, placements):
    """Replace the level's draft for these terms with `placements`."""
    numbers = [t["number"] for t in terms]
    SchemeEntry.objects.filter(level=level, term__in=numbers, is_draft=True).delete()
    new, orders = [], {}
    for term, week, day, item in placements:
        kind, _sep, pk = item.partition(":")
        field = SchemeEntry.FIELD_FOR.get(kind)
        orders[(term, week, day)] = order = orders.get((term, week, day), 0) + 1
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
    """Plan `terms` ([{"number", "weeks", "break_after"}]) for `level` and save
    it as the draft. {"count", "source": "ai" | "rules", "message"}."""
    items = catalogue(level, terms)
    if not items:
        return {"count": 0, "source": "", "message": f"There's no content for {level} to plan with yet."}
    source, message, placements = "rules", "", []
    if use_ai:
        try:
            placements = clean_plan(ai_plan(level, terms, items, note), items, terms)
            source = "ai"
            if not placements:
                message = "The AI planner's answer had nothing usable, so the plan was made by rule."
        except PlanError as error:
            logger.warning("Scheme builder for %s: %s", level, error)
            message = ("No OpenAI key is set, so the plan was made by rule."
                       if "No OpenAI key" in str(error) else "The AI planner didn't answer, so the plan was made by rule.")
    if not placements:
        source = "rules"
        placements = clean_plan(rule_plan(terms, items), items, terms)
    count = save_draft(level, terms, placements)
    return {"count": count, "source": source, "message": message}
