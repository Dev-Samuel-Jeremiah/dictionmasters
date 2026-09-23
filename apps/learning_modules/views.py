"""
Views for the Learning Modules pathway: Module > Term > Week > Day,
where a Day holds a short list of LessonItems rather than being one
lesson itself.

Terms and Weeks unlock in order — see _progress_chain, which is the
one place that decides locked/active/done for a list of siblings.
Nothing is stored: status is recomputed from DayProgress on every
request, which is cheap at this scale and means it's never stale.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import DAY_CHOICES, Day, DayProgress, LearningModule, LessonItem, Week

DAY_SLUGS = {slug for slug, _label in DAY_CHOICES}


def _completed_day_ids(user, module):
    return set(
        DayProgress.objects.filter(user=user, day__week__term__module=module).values_list(
            "day_id", flat=True
        )
    )


def _module_tree(module):
    """Terms, with their weeks and published days, prefetched in one go."""
    return module.terms.order_by("order", "id").prefetch_related(
        Prefetch(
            "weeks",
            queryset=Week.objects.order_by("number").prefetch_related(
                Prefetch("days", queryset=Day.objects.filter(is_published=True).order_by("order", "id"))
            ),
        )
    )


def _progress(day_ids, completed_ids):
    total = len(day_ids)
    done = sum(1 for d in day_ids if d in completed_ids)
    percent = round(done * 100 / total) if total else 0
    return {"total": total, "done": done, "percent": percent}


def _progress_chain(items, get_day_ids, completed_ids, label):
    """Attach a locked/active/done status to each item in order — each
    one stays locked until the one before it is fully complete. An
    empty item (no days yet) doesn't block what follows it."""
    cards = []
    unlocked = True
    for item in items:
        day_ids = get_day_ids(item)
        prog = _progress(day_ids, completed_ids)
        complete = prog["total"] == 0 or prog["done"] == prog["total"]
        status = "locked" if not unlocked else ("done" if complete and prog["total"] else "active")
        cards.append({label: item, "status": status, **prog})
        unlocked = unlocked and complete
    return cards


def _flatten(terms):
    """Every (term, week, day) in the module, in order — regardless of lock state."""
    return [
        {"term": term, "week": week, "day": day}
        for term in terms
        for week in term.weeks.all()
        for day in week.days.all()
    ]


def _reachable_flat(terms, completed_ids):
    """Every (term, week, day) that sits inside an unlocked term and an unlocked week."""
    flat = []
    term_cards = _progress_chain(
        terms, lambda t: [d.id for w in t.weeks.all() for d in w.days.all()], completed_ids, "term"
    )
    for tcard in term_cards:
        if tcard["status"] == "locked":
            break
        week_cards = _progress_chain(
            list(tcard["term"].weeks.all()), lambda w: [d.id for d in w.days.all()], completed_ids, "week"
        )
        for wcard in week_cards:
            if wcard["status"] == "locked":
                break
            for day in wcard["week"].days.all():
                flat.append({"term": tcard["term"], "week": wcard["week"], "day": day})
    return flat


def _term_status(module, term, completed_ids):
    terms = list(_module_tree(module))
    cards = _progress_chain(
        terms, lambda t: [d.id for w in t.weeks.all() for d in w.days.all()], completed_ids, "term"
    )
    return next((c["status"] for c in cards if c["term"].id == term.id), "locked")


def _week_status(term, week, completed_ids):
    weeks = term.weeks.order_by("number").prefetch_related(
        Prefetch("days", queryset=Day.objects.filter(is_published=True).order_by("order", "id"))
    )
    cards = _progress_chain(list(weeks), lambda w: [d.id for d in w.days.all()], completed_ids, "week")
    return next((c["status"] for c in cards if c["week"].id == week.id), "locked")


@login_required
def hub(request):
    modules = LearningModule.objects.filter(is_published=True).order_by("order", "name")
    module_cards = []
    for module in modules:
        terms = list(_module_tree(module))
        completed_ids = _completed_day_ids(request.user, module)
        flat = _flatten(terms)
        module_cards.append({
            "module": module,
            "term_count": len(terms),
            "progress": _progress([e["day"].id for e in flat], completed_ids),
        })
    # The first module with days still to do is where to carry on.
    current = next((c for c in module_cards if c["progress"]["done"] < c["progress"]["total"]), None)
    for card in module_cards:
        card["is_current"] = card is current
        card["is_done"] = bool(card["progress"]["total"]) and card["progress"]["done"] == card["progress"]["total"]
    total = sum(c["progress"]["total"] for c in module_cards)
    done = sum(c["progress"]["done"] for c in module_cards)
    return render(request, "learning_modules/hub.html", {
        "module_cards": module_cards,
        "current_card": current,
        "overall": {
            "modules": len(module_cards),
            "terms": sum(c["term_count"] for c in module_cards),
            "total": total,
            "done": done,
            "percent": round(done * 100 / total) if total else 0,
        },
    })


@login_required
def module_detail(request, module_slug):
    module = get_object_or_404(LearningModule, slug=module_slug, is_published=True)
    terms = list(_module_tree(module))
    completed_ids = _completed_day_ids(request.user, module)
    flat = _flatten(terms)
    progress = _progress([e["day"].id for e in flat], completed_ids)

    term_cards = _progress_chain(
        terms, lambda t: [d.id for w in t.weeks.all() for d in w.days.all()], completed_ids, "term"
    )

    reachable = _reachable_flat(terms, completed_ids)
    continue_entry = next((e for e in reachable if e["day"].id not in completed_ids), None) or (
        reachable[0] if reachable else None
    )

    context = {
        "module": module,
        "term_cards": term_cards,
        "progress": progress,
        "continue_entry": continue_entry,
    }
    return render(request, "learning_modules/module_detail.html", context)


@login_required
def term_detail(request, module_slug, term_slug):
    module = get_object_or_404(LearningModule, slug=module_slug, is_published=True)
    term = get_object_or_404(module.terms, slug=term_slug)
    completed_ids = _completed_day_ids(request.user, module)

    if _term_status(module, term, completed_ids) == "locked":
        messages.warning(request, "Complete the term before this one to unlock it.")
        return redirect("learning_modules:module_detail", module_slug=module_slug)

    weeks = term.weeks.order_by("number").prefetch_related(
        Prefetch("days", queryset=Day.objects.filter(is_published=True).order_by("order", "id"))
    )
    week_cards = _progress_chain(list(weeks), lambda w: [d.id for d in w.days.all()], completed_ids, "week")

    return render(
        request,
        "learning_modules/term_detail.html",
        {
            "module": module,
            "term": term,
            "week_cards": week_cards,
            "current_week": next((c for c in week_cards if c["status"] == "active"), None),
            "progress": _progress(
                [d.id for c in week_cards for d in c["week"].days.all()], completed_ids
            ),
        },
    )


@login_required
def week_detail(request, module_slug, term_slug, week_slug):
    module = get_object_or_404(LearningModule, slug=module_slug, is_published=True)
    term = get_object_or_404(module.terms, slug=term_slug)
    completed_ids = _completed_day_ids(request.user, module)

    if _term_status(module, term, completed_ids) == "locked":
        messages.warning(request, "Complete the term before this one to unlock it.")
        return redirect("learning_modules:module_detail", module_slug=module_slug)

    week = get_object_or_404(term.weeks, slug=week_slug)
    if _week_status(term, week, completed_ids) == "locked":
        messages.warning(request, "Complete the week before this one to unlock it.")
        return redirect("learning_modules:term_detail", module_slug=module_slug, term_slug=term_slug)

    days = week.days.filter(is_published=True).order_by("order", "id").prefetch_related(
        Prefetch("lesson_items", queryset=LessonItem.objects.filter(is_published=True))
    )
    day_rows = [
        {
            "day": day,
            "is_complete": day.id in completed_ids,
            "item_count": len(day.lesson_items.all()),
            "has_video": any(i.video_source for i in day.lesson_items.all()),
            "has_audio": any(i.audio_source for i in day.lesson_items.all()),
        }
        for day in days
    ]

    return render(
        request,
        "learning_modules/week_detail.html",
        {
            "module": module,
            "term": term,
            "week": week,
            "day_rows": day_rows,
            "next_row": next((row for row in day_rows if not row["is_complete"]), None),
            "progress": _progress([row["day"].id for row in day_rows], completed_ids),
        },
    )


@login_required
def day_detail(request, module_slug, term_slug, week_slug, day_name):
    if day_name not in DAY_SLUGS:
        raise Http404("That day doesn't exist.")

    module = get_object_or_404(LearningModule, slug=module_slug, is_published=True)
    term = get_object_or_404(module.terms, slug=term_slug)
    completed_ids = _completed_day_ids(request.user, module)

    if _term_status(module, term, completed_ids) == "locked":
        messages.warning(request, "Complete the term before this one to unlock it.")
        return redirect("learning_modules:module_detail", module_slug=module_slug)

    week = get_object_or_404(term.weeks, slug=week_slug)
    if _week_status(term, week, completed_ids) == "locked":
        messages.warning(request, "Complete the week before this one to unlock it.")
        return redirect("learning_modules:term_detail", module_slug=module_slug, term_slug=term_slug)

    day = get_object_or_404(week.days, day_name=day_name, is_published=True)
    lesson_items = day.lesson_items.filter(is_published=True).order_by("order", "id")

    terms = list(_module_tree(module))
    reachable = _reachable_flat(terms, completed_ids)
    index = next((i for i, e in enumerate(reachable) if e["day"].id == day.id), None)
    prev_entry = reachable[index - 1] if index else None
    next_entry = reachable[index + 1] if index is not None and index < len(reachable) - 1 else None

    sibling_days = {d.day_name: d for d in week.days.filter(is_published=True)}

    context = {
        "module": module,
        "term": term,
        "week": week,
        "day": day,
        "lesson_items": lesson_items,
        "is_complete": day.id in completed_ids,
        "prev_entry": prev_entry,
        "next_entry": next_entry,
        "day_choices": DAY_CHOICES,
        "sibling_days": sibling_days,
        "done_day_names": {name for name, d in sibling_days.items() if d.id in completed_ids},
    }
    return render(request, "learning_modules/day_detail.html", context)


@login_required
@require_POST
def toggle_complete(request, module_slug, term_slug, week_slug, day_name):
    module = get_object_or_404(LearningModule, slug=module_slug, is_published=True)
    term = get_object_or_404(module.terms, slug=term_slug)
    week = get_object_or_404(term.weeks, slug=week_slug)
    day = get_object_or_404(week.days, day_name=day_name)

    DayProgress.objects.get_or_create(user=request.user, day=day)

    return redirect(
        "learning_modules:day_detail",
        module_slug=module_slug,
        term_slug=term_slug,
        week_slug=week_slug,
        day_name=day_name,
    )
