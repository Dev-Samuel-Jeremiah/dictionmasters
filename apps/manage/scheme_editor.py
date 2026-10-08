"""
The scheme of work editor in the control room: one level's term as a
timetable, week 1 to 14, Monday to Friday.

Staff put content on it one piece at a time (week, day, content), move it
up or down within its day, take it off, or fill the weeks in one go from a
whole set — a level's EchoSpell groups one a week, a module's days one a
school day, the level's dialogues on the weeks they were written for. What
is on it is exactly what the level's students see and may open
(apps/scheme/timetable.py).
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.assessments.models import Assessment
from apps.assembly_recitals.models import Recital
from apps.book.models import ACADEMY, TRICKS
from apps.conversational_dialogue.models import Dialogue
from apps.diction_library.models import LibraryItem
from apps.echospell.models import LEVEL_NAME_CHOICES, Group
from apps.learning_modules.models import Day, LearningModule
from apps.reading_club.models import Book, Chapter
from apps.scheme.models import DAY_CHOICES, TERM_CHOICES, WEEK_CHOICES, SchemeEntry
from apps.tricks.progress import lessons_in_order

from .views import _base_context, staff_only

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
LAST_WEEK = WEEK_CHOICES[-1][0]
K = SchemeEntry.Kind


def _content_choices(level):
    """[(group label, [(value, label)])] for the Add form: everything that
    can go on this level's scheme. Values are "kind:pk"."""
    modules = (Day.objects.filter(is_published=True, week__term__module__is_published=True)
               .select_related("week__term__module")
               .order_by("week__term__module__order", "week__term__module__name", "week__term__order",
                         "week__term__id", "week__number", "order"))
    return [
        ("EchoSpell groups", [(f"{K.GROUP}:{g.pk}", f"Group {g.number}{' — ' + g.title if g.title else ''}")
                              for g in Group.objects.filter(level__name=level).order_by("number")]),
        ("Learning Modules days", [(f"{K.MODULE_DAY}:{d.pk}",
                                    f"{d.week.term.module.name}: {d.week.term.name}, {d.week.display_name}, {d.get_day_name_display()}")
                                   for d in modules]),
        ("Conversational Dialogue", [(f"{K.DIALOGUE}:{d.pk}", f"Term {d.term}, Week {d.week}, {d.get_day_display()}: {d.title}")
                                     for d in Dialogue.objects.filter(level__name=level)]),
        ("44 Academy", [(f"{K.SOUND}:{s.pk}", s.name) for s in lessons_in_order(ACADEMY)]),
        ("Tricks to Sound Fluent", [(f"{K.TRICK}:{s.pk}", s.name) for s in lessons_in_order(TRICKS)]),
        ("Reading Club", [(f"{K.CHAPTER}:{c.pk}", f"{c.term.book.title}: {c.term.name}, {c.title}")
                          for c in Chapter.objects.select_related("term__book").order_by("term__book__order", "term__order", "number", "id")]),
        ("Assembly Recitals", [(f"{K.RECITAL}:{r.pk}", f"{r.section.name}: {r.title}")
                               for r in Recital.objects.select_related("section").order_by("section__order", "order")]),
        ("Diction Library", [(f"{K.LIBRARY}:{i.pk}", i.title) for i in LibraryItem.objects.filter(school__isnull=True).order_by("title")]),
        ("Assessments", [(f"{K.ASSESSMENT}:{a.pk}", f"{a.title} ({a.get_kind_display()})")
                         for a in Assessment.objects.filter(level__in=[level, ""]).order_by("kind", "title")]),
        ("Other", [(f"{K.DAILY_PRACTICE}:", "Daily Practice")]),
    ]


def _fill_sets(level, term):
    """[(value, label)] of the sets the weeks can be filled from."""
    sets = [("groups", f"{level} EchoSpell groups, in number order"),
            ("dialogues", f"{level} Conversational Dialogues for this term, on their own weeks and days"),
            ("academy", "44 Academy sounds, in order"),
            ("tricks", "Tricks to Sound Fluent lessons, in order")]
    sets += [(f"module:{m.pk}", f"Learning Modules: {m.name}, every day in order")
             for m in LearningModule.objects.order_by("order", "name")]
    sets += [(f"book:{b.pk}", f"Reading Club: {b.title}, every chapter in order") for b in Book.objects.order_by("order", "title")]
    return sets


def _set_items(name, level, term):
    """(kind, field, items) for a fill set."""
    if name == "groups":
        return K.GROUP, "group", list(Group.objects.filter(level__name=level).order_by("number"))
    if name == "academy":
        return K.SOUND, "sound", lessons_in_order(ACADEMY)
    if name == "tricks":
        return K.TRICK, "sound", lessons_in_order(TRICKS)
    if name.startswith("module:"):
        return K.MODULE_DAY, "module_day", list(
            Day.objects.filter(week__term__module_id=name.split(":")[1], is_published=True)
            .order_by("week__term__order", "week__term__id", "week__number", "order"))
    if name.startswith("book:"):
        return K.CHAPTER, "chapter", list(
            Chapter.objects.filter(term__book_id=name.split(":")[1]).order_by("term__order", "number", "id"))
    return None, None, []


def _next_order(level, term, week, day):
    found = SchemeEntry.objects.filter(level=level, term=term, week=week, day=day).aggregate(n=Max("order"))["n"]
    return (found or 0) + 1


def _back(level, term):
    return redirect(f"{reverse('manage:scheme_editor')}?level={level}&term={term}")


@staff_only
def scheme_editor(request):
    level = request.GET.get("level") or request.POST.get("level") or LEVELS[1]
    level = level if level in LEVELS else LEVELS[1]
    raw_term = request.GET.get("term") or request.POST.get("term") or "1"
    term = int(raw_term) if raw_term in {"1", "2", "3"} else 1

    if request.method == "POST":
        action = request.POST.get("action")
        entries = SchemeEntry.objects.filter(level=level, term=term)
        if action == "add":
            _add(request, level, term)
        elif action in ("up", "down", "remove"):
            entry = entries.filter(pk=request.POST.get("entry")).first()
            if entry and action == "remove":
                entry.delete()
                messages.success(request, f"Taken off: {entry.title}.")
            elif entry:
                _move(entry, -1 if action == "up" else 1)
        elif action == "fill":
            _fill(request, level, term)
        elif action == "clear":
            count = entries.count()
            entries.delete()
            messages.success(request, f"{level}, {dict(TERM_CHOICES)[term]}: {count} entries taken off.")
        return _back(level, term)

    rows = {}
    for entry in (SchemeEntry.objects.filter(level=level, term=term)
                  .select_related("group", "module_day__week__term__module", "dialogue", "sound", "chapter",
                                  "recital", "library_item", "assessment")):
        rows.setdefault(entry.week, []).append(entry)
    day_index = {key: i for i, (key, _label) in enumerate(DAY_CHOICES)}
    weeks = [{"number": n, "entries": sorted(rows.get(n, []), key=lambda e: (day_index.get(e.day, 0), e.order, e.pk))}
             for n, _label in WEEK_CHOICES]
    return render(request, "manage/scheme_editor.html", _base_context(
        request, "scheme-editor", level=level, term=term, levels=LEVELS, terms=TERM_CHOICES,
        weeks=weeks, days=DAY_CHOICES, week_choices=WEEK_CHOICES,
        content_choices=_content_choices(level), fill_sets=_fill_sets(level, term),
        total=sum(len(w["entries"]) for w in weeks),
    ))


def _add(request, level, term):
    try:
        week = int(request.POST.get("week", ""))
        kind, _sep, pk = request.POST.get("content", "").partition(":")
    except ValueError:
        messages.error(request, "Choose a week and something to add.")
        return
    day = request.POST.get("day", "")
    field = SchemeEntry.FIELD_FOR.get(kind, "missing")
    if field == "missing" or day not in dict(DAY_CHOICES) or not 1 <= week <= LAST_WEEK:
        messages.error(request, "Choose a week, a day and something to add.")
        return
    entry = SchemeEntry(level=level, term=term, week=week, day=day, kind=kind,
                        order=_next_order(level, term, week, day))
    if field:
        if not pk.isdigit():
            messages.error(request, "Choose something to add.")
            return
        setattr(entry, f"{field}_id", int(pk))
    entry.full_clean()
    entry.save()
    messages.success(request, f"Added to Week {week}: {entry.title}.")


def _move(entry, step):
    """Swap with its neighbour on the same day."""
    same_day = list(SchemeEntry.objects.filter(level=entry.level, term=entry.term, week=entry.week, day=entry.day)
                    .order_by("order", "pk"))
    at = same_day.index(entry)
    other = at + step
    if 0 <= other < len(same_day):
        same_day[at], same_day[other] = same_day[other], same_day[at]
        with transaction.atomic():
            for order, item in enumerate(same_day, start=1):
                if item.order != order:
                    SchemeEntry.objects.filter(pk=item.pk).update(order=order)


def _fill(request, level, term):
    """Put a whole set on the timetable, in order, from a starting week."""
    name = request.POST.get("set", "")
    try:
        start = int(request.POST.get("start_week", "1"))
        skip = max(int(request.POST.get("start_at", "1") or 1) - 1, 0)
        limit = int(request.POST.get("how_many") or 0)
    except ValueError:
        messages.error(request, "Weeks and numbers must be whole numbers.")
        return
    pace = request.POST.get("pace", "week")
    day = request.POST.get("day", "")
    new = []
    if name == "dialogues":
        # Dialogues were written for a week and day of each term: keep them there.
        for dialogue in Dialogue.objects.filter(level__name=level, term=term):
            if dialogue.week <= LAST_WEEK:
                new.append(SchemeEntry(level=level, term=term, week=dialogue.week, day=dialogue.day,
                                       kind=K.DIALOGUE, dialogue=dialogue))
    else:
        kind, field, items = _set_items(name, level, term)
        if kind is None:
            messages.error(request, "Choose what to fill the weeks with.")
            return
        items = items[skip:]
        if limit:
            items = items[:limit]
        for i, item in enumerate(items):
            if pace == "day":
                week, on = start + i // 5, WEEKDAYS[i % 5]
            else:
                week, on = start + i, day
            if week > LAST_WEEK:
                break
            new.append(SchemeEntry(level=level, term=term, week=week, day=on, kind=kind, **{field: item}))
    # Each goes after anything already on its day.
    tops = {}
    for row in (SchemeEntry.objects.filter(level=level, term=term).values("week", "day")
                .annotate(top=Max("order"))):
        tops[(row["week"], row["day"])] = row["top"] or 0
    for entry in new:
        tops[(entry.week, entry.day)] = entry.order = tops.get((entry.week, entry.day), 0) + 1
    SchemeEntry.objects.bulk_create(new)
    messages.success(request, f"{len(new)} entr{'y' if len(new) == 1 else 'ies'} put on {level}, {dict(TERM_CHOICES)[term]}.")
