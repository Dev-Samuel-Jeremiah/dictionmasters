"""
Tricks to Sound Fluent is taken in order. Trick 1 is open to everyone;
each trick after it opens only once the one before it is complete:

  1. finish it — open the trick, and every tab of it that has something in it;
  2. pass its assessment — the pass mark is the assessment's own.

A trick with no assessment yet (none linked, unpublished, or without
questions) is complete as soon as it is finished, so a missing test
never shuts learners out. Spoken answers wait for a teacher, so a
speaking assessment counts once it has been marked and passed. Staff see
every trick open, to check the content.
"""

from django.db.models import Count

from apps.assessments.models import Attempt
from apps.book.models import SECTION_CHOICES, TRICKS, Sound

from .models import TrickProgress

# How to tell whether a tab has anything in it.
TAB_CONTENT = {
    "lens": "articulation", "word-bank": "word_bank_entries", "sentence-practice": "sentence_practices",
    "passage": "passages", "conversations": "conversations", "twisters": "tongue_twisters",
    "minimal-pairs": "minimal_pairs", "external-links": "external_links",
}
TAB_LABELS = dict(SECTION_CHOICES)
FINISHED = (Attempt.Status.SUBMITTED, Attempt.Status.MARKED)


def tricks_in_order():
    """Published tricks, Trick 1 first."""
    return list(
        Sound.objects.in_programme(TRICKS).filter(is_published=True)
        .order_by("category__order", "order", "name")
        .annotate(**{f"n_{slug.replace('-', '_')}": Count(rel, distinct=True) for slug, rel in TAB_CONTENT.items()})
        .annotate(n_videos=Count("videos", distinct=True))
        .select_related("trick_assessment")
    )


def tabs_to_finish(trick):
    """The tabs of this trick that have something in them."""
    videos = set(trick.videos.values_list("section", flat=True))
    needed = []
    for slug, _label in SECTION_CHOICES:
        count = getattr(trick, f"n_{slug.replace('-', '_')}", None)
        if count is None:
            count = getattr(trick, TAB_CONTENT[slug]).count() if slug != "lens" else int(hasattr(trick, "articulation"))
        if count or slug in videos:
            needed.append(slug)
    return needed


def usable_assessment(trick):
    assessment = getattr(trick, "trick_assessment", None)
    if assessment and assessment.is_published and assessment.questions.exists():
        return assessment
    return None


def record_tab(user, trick, tab):
    if not user.is_authenticated:
        return
    progress, _ = TrickProgress.objects.get_or_create(user=user, trick=trick)
    if tab not in progress.tabs_seen:
        progress.tabs_seen = [*progress.tabs_seen, tab]
        progress.save(update_fields=["tabs_seen", "updated_at"])


def journey(user):
    """Every trick with where this learner stands on it:
    state is "done", "current" (open, not yet complete) or "locked"."""
    tricks = tricks_in_order()
    seen = dict(TrickProgress.objects.filter(user=user, trick__in=tricks).values_list("trick_id", "tabs_seen"))
    attempts = {}
    for attempt in (Attempt.objects.filter(user=user, assessment__trick__in=tricks)
                    .exclude(status=Attempt.Status.IN_PROGRESS).order_by("submitted_at")):
        attempts.setdefault(attempt.assessment.trick_id, []).append(attempt)

    steps, open_so_far = [], True
    for number, trick in enumerate(tricks, start=1):
        needed = tabs_to_finish(trick)
        done_tabs = [tab for tab in needed if tab in seen.get(trick.pk, [])]
        assessment = usable_assessment(trick)
        tried = attempts.get(trick.pk, [])
        passed = any(a.passed and a.status in FINISHED for a in tried)
        waiting = any(a.status == Attempt.Status.AWAITING for a in tried)
        # Opened at least once, and every part with something in it seen.
        finished = trick.pk in seen and len(done_tabs) == len(needed)
        complete = finished and (passed if assessment else True)
        unlocked = open_so_far or user.is_staff
        steps.append({
            "trick": trick, "number": number,
            "state": "done" if (unlocked and complete) else ("current" if unlocked else "locked"),
            "unlocked": unlocked, "finished": finished, "complete": complete,
            "tabs": [{"slug": tab, "label": TAB_LABELS[tab], "seen": tab in done_tabs} for tab in needed],
            "tabs_left": len(needed) - len(done_tabs),
            "assessment": assessment, "passed": passed, "waiting": waiting,
            "best": max((a.percent for a in tried if a.status in FINISHED), default=None),
            "last": tried[-1] if tried else None,
        })
        open_so_far = open_so_far and complete
    for step, following in zip(steps, steps[1:] + [None]):
        step["next"] = following
    return steps


def step_for(user, trick):
    return next((step for step in journey(user) if step["trick"].pk == trick.pk), None)


def locked_by(user, trick):
    """The step that has to be completed first, or None if this trick is open."""
    steps = journey(user)
    for index, step in enumerate(steps):
        if step["trick"].pk == trick.pk:
            if step["unlocked"]:
                return None
            return next(s for s in steps[:index] if not s["complete"])
    return None
