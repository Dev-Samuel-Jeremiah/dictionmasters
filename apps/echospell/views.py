"""
Views for EchoSpell: Level > Group > Card.

A "card" is a Category assigned to the group's Level. For a
"words"-kind category, the card's content is its own set of
CardLesson rows — scoped to that exact (group, category) pair, never
shared with any other category — and the view's job is just to frame
that same word list differently per category (scrambled for Puzzle,
blanked for Missing Letter, and so on).
"""

import json
import random

from apps.accounts.access import limit_to_levels, require_level

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import qr
from .activity_kinds import MODE_CHOICE, MODE_ORDER, MODE_RECORD
from .marking import feedback_for, grade_sentence_use, mark_response
from .models import (
    Activity,
    ActivityAttempt,
    ActivityResponse,
    CardLesson,
    CardPosition,
    GroupProgress,
    Level,
)


def _completed_group_ids(user, level):
    return set(
        GroupProgress.objects.filter(user=user, group__level=level).values_list("group_id", flat=True)
    )


def _missing_letters(word, rng):
    """One word with about a third of its letters blanked out."""
    chars = list(word)
    letter_positions = [i for i, ch in enumerate(chars) if ch.isalpha()]
    if not letter_positions:
        return word
    hide_count = max(1, len(letter_positions) // 3)
    for i in rng.sample(letter_positions, min(hide_count, len(letter_positions))):
        chars[i] = "_"
    return "".join(chars)


def _scrambled(word, rng):
    """One word's letters shuffled — falls back to the original if that
    shuffle happens to reproduce it (only matters for very short words)."""
    letters = list(word)
    for _ in range(6):
        rng.shuffle(letters)
        if "".join(letters).lower() != word.lower() or len(word) < 3:
            break
    return "".join(letters)


def _decoys(entry, all_entries, rng, count=3):
    """Individual words drawn from the rest of this card, for a
    multiple-choice option — flattened, since any entry may hold more
    than one word sharing its audio."""
    this_entry = {w.lower() for w in entry.word_list}
    pool = [w for other in all_entries for w in other.word_list if w.lower() not in this_entry]
    rng.shuffle(pool)
    return pool[:count]


@login_required
def hub(request):
    # A school's teachers and students see their own level only.
    levels = limit_to_levels(
        Level.objects.filter(is_published=True), request.user, field="name", allow_blank=False
    ).order_by("order", "name")
    level_cards = []
    for level in levels:
        groups = list(level.groups.all())
        completed_ids = _completed_group_ids(request.user, level)
        total = len(groups)
        done = sum(1 for g in groups if g.id in completed_ids)
        level_cards.append({
            "level": level,
            "group_count": total,
            "card_count": CardLesson.objects.filter(group__level=level, is_published=True).count(),
            "progress": {
                "total": total, "done": done,
                "percent": round(done * 100 / total) if total else 0,
            },
        })
    total_groups = sum(card["group_count"] for card in level_cards)
    done_groups = sum(card["progress"]["done"] for card in level_cards)
    # The first level with groups still to finish is where to carry on.
    current = next((c for c in level_cards if c["progress"]["done"] < c["group_count"]), None)
    for card in level_cards:
        card["is_current"] = card is current
        card["is_done"] = bool(card["group_count"]) and card["progress"]["done"] == card["group_count"]
    return render(request, "echospell/hub.html", {
        "level_cards": level_cards,
        "current_card": current,
        "overall": {
            "levels": len(level_cards),
            "groups": total_groups,
            "done": done_groups,
            "cards": sum(card["card_count"] for card in level_cards),
            "percent": round(done_groups * 100 / total_groups) if total_groups else 0,
        },
    })


@login_required
def level_detail(request, level_slug):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    groups = list(level.groups.all())
    completed_ids = _completed_group_ids(request.user, level)

    current_id = next((g.id for g in groups if g.id not in completed_ids), None)
    group_rows = [
        {
            "group": g,
            "is_complete": g.id in completed_ids,
            "is_current": g.id == current_id,
            "card_count": g.lessons.filter(is_published=True).count(),
            "activity_count": g.activities.filter(is_published=True).count(),
        }
        for g in groups
    ]
    done = sum(1 for row in group_rows if row["is_complete"])

    context = {
        "level": level,
        "group_rows": group_rows,
        "current_row": next((row for row in group_rows if row["is_current"]), None),
        "progress": {
            "total": len(groups), "done": done,
            "percent": round(done * 100 / len(groups)) if groups else 0,
        },
    }
    return render(request, "echospell/level_detail.html", context)


@login_required
def group_detail(request, level_slug, group_slug):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    completed_ids = _completed_group_ids(request.user, level)

    groups = list(level.groups.all())
    index = next((i for i, g in enumerate(groups) if g.id == group.id), None)
    prev_group = groups[index - 1] if index else None
    next_group = groups[index + 1] if index is not None and index < len(groups) - 1 else None

    context = {
        "level": level,
        "group": group,
        "categories": level.categories.all(),
        "is_complete": group.id in completed_ids,
        "prev_group": prev_group,
        "next_group": next_group,
        "card_count": group.lessons.filter(is_published=True).count(),
        "activity_rows": activity_rows(request.user, activities_for(group)),
        "group_position": (index or 0) + 1,
        "group_total": len(groups),
    }
    return render(request, "echospell/group_detail.html", context)


@login_required
def card_detail(request, level_slug, group_slug, category_slug):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    category = get_object_or_404(level.categories, slug=category_slug)

    context = {"level": level, "group": group, "category": category}

    # Remember this card page for "Pick up where you left off". The exact
    # card on it is filled in by save_card_position as they work down it.
    position, created = CardPosition.objects.get_or_create(
        user=request.user, defaults={"group": group, "category": category}
    )
    if not created and (position.group_id, position.category_id) != (group.id, category.id):
        position.group, position.category, position.lesson = group, category, None
        position.save()

    if category.kind == "passage":
        context["passage"] = getattr(group, "passage", None)
    elif category.kind == "dialogue":
        dialogue = getattr(group, "dialogue", None)
        context["dialogue"] = dialogue
        context["lines"] = dialogue.lines.all() if dialogue else []
    else:
        entries = list(
            CardLesson.objects.filter(group=group, category=category, is_published=True)
            .order_by("order", "id")
        )
        # Seeded per group+category so the puzzle/blanks/decoys stay the
        # same across a single learner's visits instead of reshuffling
        # every request.
        rng = random.Random(f"{group.id}:{category.slug}")

        cards = []
        for entry in entries:
            card = {"entry": entry}
            if category.slug == "missing-letter":
                card["display_list"] = [_missing_letters(w, rng) for w in entry.word_list]
            elif category.slug == "puzzle":
                card["display_list"] = [_scrambled(w, rng) for w in entry.word_list]
            elif category.slug == "listen-and-circle":
                correct = entry.word_list
                decoys = _decoys(entry, entries, rng, count=max(1, 4 - len(correct)))
                options = decoys + correct
                rng.shuffle(options)
                card["options"] = options
            cards.append(card)
        context["cards"] = cards

        context["entries"] = entries

    # Its own QR code, for printing beside this card in the book. Shown to
    # the people who make the books, not to every learner.
    context["card_url"] = qr.public_url(
        reverse("echospell:card_detail", args=[level.slug, group.slug, category.slug])
    )
    context["show_qr"] = _makes_materials(request.user)

    return render(request, "echospell/card_detail.html", context)


def _makes_materials(user):
    """Only Diction Masters' own staff make the printed books, so only they
    see a card's QR code. Everyone else — school admins, teachers,
    learners — simply scans the code in the book."""
    return bool(user.is_staff or user.is_superuser)


def _card_urls(request, level, group):
    """(category, address) for every card in a group, in the order they're shown."""
    return [
        (category, qr.public_url(
            reverse("echospell:card_detail", args=[level.slug, group.slug, category.slug])
        ))
        for category in level.categories.all()
    ]


@login_required
def card_qr_png(request, level_slug, group_slug, category_slug):
    """The card's QR code as a PNG, to drop into a book layout."""
    if not _makes_materials(request.user):
        raise Http404("No such page.")
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    category = get_object_or_404(level.categories, slug=category_slug)
    address = qr.public_url(
        reverse("echospell:card_detail", args=[level.slug, group.slug, category.slug])
    )
    response = HttpResponse(qr.png(address), content_type="image/png")
    name = f"qr-{level.slug}-{group.slug}-{category.slug}.png"
    response["Content-Disposition"] = f'inline; filename="{name}"'
    response["Cache-Control"] = "private, max-age=86400"
    return response


@login_required
def group_qr_sheet(request, level_slug, group_slug):
    """Every card in one group, with its code, laid out to print and cut up."""
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    if not _makes_materials(request.user):
        raise Http404("No such page.")
    return render(request, "echospell/qr_sheet.html", {
        "level": level,
        "group": group,
        "cards": [{"category": category, "url": address} for category, address in _card_urls(request, level, group)],
    })


@login_required
@require_POST
def save_card_position(request):
    """The card a learner is on, sent from the card page as they scroll
    or tap. Quietly ignores anything they couldn't open themselves."""
    lesson_id = request.POST.get("lesson", "")
    lesson = (
        CardLesson.objects.filter(pk=lesson_id, is_published=True, group__level__is_published=True)
        .select_related("group__level")
        .first()
    ) if lesson_id.isdigit() else None
    if lesson is None or not lesson.group.level.categories.filter(pk=lesson.category_id).exists():
        return HttpResponse(status=204)
    require_level(request.user, lesson.group.level.name)
    CardPosition.objects.update_or_create(
        user=request.user, defaults={"group": lesson.group, "category": lesson.category, "lesson": lesson}
    )
    return HttpResponse(status=204)


@login_required
@require_POST
def toggle_complete(request, level_slug, group_slug):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)

    progress, created = GroupProgress.objects.get_or_create(user=request.user, group=group)
    if not created:
        progress.delete()

    return redirect("echospell:group_detail", level_slug=level_slug, group_slug=group_slug)


@login_required
@require_POST
def check_vocabulary_sentences(request):
    try:
        payload = json.loads(request.body)
        items = payload["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    results = []
    for item in items:
        word = str(item.get("word", ""))[:100]
        sentence = str(item.get("sentence", ""))[:500]
        correct, feedback = grade_sentence_use(word, sentence)
        results.append({"correct": correct, "feedback": feedback})

    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# Activities — the scored exercises hung off a level (and maybe one group)
# ---------------------------------------------------------------------------


def activities_for(group):
    """A group's published activities, in the order they're set."""
    return list(Activity.objects.filter(group=group, is_published=True).order_by("order", "id"))


def _best_attempts(user, activities):
    """The learner's highest-scoring attempt per activity, if any."""
    best = {}
    attempts = ActivityAttempt.objects.filter(user=user, activity__in=activities)
    for attempt in attempts:
        current = best.get(attempt.activity_id)
        if current is None or attempt.percent > current.percent:
            best[attempt.activity_id] = attempt
    return best


def activity_rows(user, activities):
    best = _best_attempts(user, activities)
    return [
        {"activity": a, "best": best.get(a.id), "item_count": a.items.count()}
        for a in activities
    ]


def _item_rows(activity, items):
    """Per-item view data: choices shuffled out of their authored order,
    and sentence-builder words jumbled — both stable per item."""
    rows = []
    for item in items:
        row = {"item": item, "options": [], "tokens": []}
        if activity.mode == MODE_CHOICE:
            options = item.option_list
            random.Random(item.id).shuffle(options)
            row["options"] = options
        elif activity.mode == MODE_ORDER:
            row["tokens"] = item.token_list
        rows.append(row)
    return rows


@login_required
def activity_detail(request, level_slug, group_slug, activity_slug):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    activity = get_object_or_404(Activity, group=group, slug=activity_slug, is_published=True)
    items = list(activity.items.all())

    if request.method == "POST" and items:
        attempt = ActivityAttempt.objects.create(user=request.user, activity=activity)
        is_recording = activity.mode == MODE_RECORD
        for item in items:
            given = request.POST.get(f"item-{item.id}", "").strip()[:1000]
            recording = request.FILES.get(f"recording-{item.id}")
            ActivityResponse.objects.create(
                attempt=attempt,
                item=item,
                given=given,
                is_correct=None if is_recording else mark_response(activity.kind_spec, item, given),
                recording=recording or "",
            )
        attempt.recalculate()
        attempt.save()
        return redirect(
            "echospell:activity_result",
            level_slug=level.slug, group_slug=group.slug,
            activity_slug=activity.slug, attempt_id=attempt.id,
        )

    return render(request, "echospell/activity_detail.html", {
        "level": level,
        "group": group,
        "activity": activity,
        "item_rows": _item_rows(activity, items),
        "buckets": activity.bucket_list,
        "previous": _best_attempts(request.user, [activity]).get(activity.id),
    })


@login_required
def activity_result(request, level_slug, group_slug, activity_slug, attempt_id):
    level = get_object_or_404(Level, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    group = get_object_or_404(level.groups, slug=group_slug)
    activity = get_object_or_404(Activity, group=group, slug=activity_slug)
    attempt = get_object_or_404(ActivityAttempt, pk=attempt_id, activity=activity, user=request.user)

    kind = activity.kind_spec
    rows = [
        {
            "response": response,
            "item": response.item,
            "feedback": feedback_for(kind, response.item, response.given, response.is_correct),
        }
        for response in attempt.responses.select_related("item")
    ]

    return render(request, "echospell/activity_result.html", {
        "level": level,
        "group": group,
        "activity": activity,
        "attempt": attempt,
        "rows": rows,
    })
