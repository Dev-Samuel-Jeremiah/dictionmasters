"""Conversational Dialogue: levels, a level's terms and weeks, a dialogue.

A school's teachers and students see only their own level
(apps/accounts/access.py); everyone else sees every level."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.access import is_level_scoped, limit_to_levels, require_level

from .models import DAY_CHOICES, TERM_CHOICES, WEEK_CHOICES, Dialogue, DialogueLevel, DialogueProgress


def _levels(user):
    levels = DialogueLevel.objects.filter(is_published=True).annotate(
        dialogue_count=Count("dialogues", filter=Q(dialogues__is_published=True))
    ).order_by("order", "name")
    return limit_to_levels(levels, user, field="name", allow_blank=False)


def _done_ids(user, level=None):
    qs = DialogueProgress.objects.filter(user=user)
    if level is not None:
        qs = qs.filter(dialogue__level=level)
    return set(qs.values_list("dialogue_id", flat=True))


@login_required
def hub(request):
    levels = list(_levels(request.user))
    if is_level_scoped(request.user) and len(levels) == 1:
        return redirect("conversational_dialogue:level", level_slug=levels[0].slug)
    done = _done_ids(request.user)
    done_by_level = dict(
        Dialogue.objects.filter(pk__in=done).values_list("level").annotate(n=Count("pk"))
    )
    for level in levels:
        level.done = done_by_level.get(level.pk, 0)
        level.percent = round(level.done * 100 / level.dialogue_count) if level.dialogue_count else 0
    return render(request, "conversational_dialogue/hub.html", {
        "levels": levels,
        "total": sum(l.dialogue_count for l in levels),
    })


@login_required
def level_detail(request, level_slug):
    level = get_object_or_404(DialogueLevel, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    dialogues = list(level.dialogues.filter(is_published=True))
    done = _done_ids(request.user, level)

    counts = {t: 0 for t, _l in TERM_CHOICES}
    for d in dialogues:
        counts[d.term] = counts.get(d.term, 0) + 1
    try:
        term = int(request.GET.get("term", 0))
    except ValueError:
        term = 0
    if term not in counts:
        term = next((t for t, _l in TERM_CHOICES if counts[t]), 1)

    weeks = []
    for number, label in WEEK_CHOICES:
        in_week = [d for d in dialogues if d.term == term and d.week == number]
        days = []
        for key, day_label in DAY_CHOICES:
            on_day = [d for d in in_week if d.day == key]
            days.append({"key": key, "label": day_label, "short": day_label[:3], "dialogues": on_day,
                         "done": bool(on_day) and all(d.pk in done for d in on_day)})
        finished = sum(1 for d in in_week if d.pk in done)
        weeks.append({
            "number": number, "label": label, "days": days, "count": len(in_week), "done": finished,
            "percent": round(finished * 100 / len(in_week)) if in_week else 0,
            "titles": [d.title for d in in_week][:3],
        })

    return render(request, "conversational_dialogue/level.html", {
        "level": level,
        "terms": [{"number": t, "label": l, "count": counts[t]} for t, l in TERM_CHOICES],
        "term": term,
        "weeks": weeks,
        "total": len(dialogues),
        "done_total": sum(1 for d in dialogues if d.pk in done),
        "can_switch": not is_level_scoped(request.user),
    })


@login_required
def dialogue_detail(request, level_slug, slug):
    level = get_object_or_404(DialogueLevel, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    dialogue = get_object_or_404(Dialogue, level=level, slug=slug, is_published=True)
    sequence = list(level.dialogues.filter(is_published=True))
    index = next((i for i, d in enumerate(sequence) if d.pk == dialogue.pk), 0)

    speakers = dialogue.speakers
    lines = [
        {"speaker": s, "text": t, "side": "b" if s in speakers and speakers.index(s) % 2 else "a",
         "initial": (s[:1] or "•").upper()}
        for s, t in dialogue.lines
    ]
    # Target words link to their Quick Words page when the library has them.
    from apps.quick_words.models import QuickWord
    found = {
        w.word.lower(): w.slug
        for w in limit_to_levels(QuickWord.objects.filter(is_published=True), request.user)
        .filter(word__in=[x for x in dialogue.words] + [x.lower() for x in dialogue.words] + [x.capitalize() for x in dialogue.words])
    }
    words = [{"word": w, "slug": found.get(w.lower())} for w in dialogue.words]

    return render(request, "conversational_dialogue/dialogue.html", {
        "level": level,
        "dialogue": dialogue,
        "lines": lines,
        "speakers": speakers,
        "words": words,
        "is_done": DialogueProgress.objects.filter(user=request.user, dialogue=dialogue).exists(),
        "prev_dialogue": sequence[index - 1] if index > 0 else None,
        "next_dialogue": sequence[index + 1] if index < len(sequence) - 1 else None,
    })


@login_required
@require_POST
def toggle_done(request, level_slug, slug):
    level = get_object_or_404(DialogueLevel, slug=level_slug, is_published=True)
    require_level(request.user, level.name)
    dialogue = get_object_or_404(Dialogue, level=level, slug=slug, is_published=True)
    entry = DialogueProgress.objects.filter(user=request.user, dialogue=dialogue).first()
    if entry:
        entry.delete()
    else:
        DialogueProgress.objects.create(user=request.user, dialogue=dialogue)
    return redirect("conversational_dialogue:dialogue", level_slug=level.slug, slug=dialogue.slug)
