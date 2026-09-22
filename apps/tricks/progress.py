"""
A programme's lessons are taken in order — 44 Academy's sounds, and
Tricks to Sound Fluent's tricks, each separately. The first lesson is
open to everyone; each one after it opens only once the one before it
is complete:

  1. finish it — open the lesson, and every tab of it that has something in it;
  2. pass its assessment — every one of its activities (any EchoSpell
     activity type: transcription, sound sort, minimal pairs, read
     aloud…), each at its own pass mark.

A recorded activity (read aloud, listen and repeat, tongue twister)
counts once it has been sent: a teacher marks it later, in the control
room, and the learner isn't kept waiting for them. A lesson with no
activities yet is complete as soon as it is finished, so missing
questions never shut learners out. Staff see every lesson open, to check
the content.
"""

from django.db.models import Count

from apps.book.models import SECTION_CHOICES, Sound, SectionVideo

from .models import LessonActivity, LessonActivityAttempt, LessonProgress

# How to tell whether a tab has anything in it: the related rows, by model.
TAB_CONTENT = {
    "lens": "articulation", "word-bank": "word_bank_entries", "sentence-practice": "sentence_practices",
    "passage": "passages", "conversations": "conversations", "twisters": "tongue_twisters",
    "minimal-pairs": "minimal_pairs", "external-links": "external_links",
}
TAB_LABELS = dict(SECTION_CHOICES)


def lessons_in_order(programme):
    """A programme's published lessons, first to last, as the lists show them."""
    return list(
        Sound.objects.in_programme(programme).filter(is_published=True)
        .select_related("category").order_by("category__order", "category__name", "category__pk", "order", "name")
    )


def _tabs_with_content(lessons):
    """{lesson id: the tabs that have something in them}, one query per tab."""
    ids = [lesson.pk for lesson in lessons]
    filled = {pk: set() for pk in ids}
    for tab, relation in TAB_CONTENT.items():
        field = Sound._meta.get_field(relation)
        model, link = field.related_model, field.field.name
        for pk in model.objects.filter(**{f"{link}__in": ids}).values_list(link, flat=True).distinct():
            filled[pk].add(tab)
    for pk, section in SectionVideo.objects.filter(sound__in=ids).values_list("sound", "section").distinct():
        filled[pk].add(section)
    return {pk: [tab for tab, _ in SECTION_CHOICES if tab in tabs] for pk, tabs in filled.items()}


def _activities_by_lesson(lessons):
    """Each lesson's published activities that have questions, in order."""
    found = {}
    for activity in (LessonActivity.objects.filter(lesson__in=lessons, is_published=True)
                     .annotate(item_count=Count("items")).filter(item_count__gt=0).order_by("order", "id")):
        found.setdefault(activity.lesson_id, []).append(activity)
    return found


def record_tab(user, lesson, tab):
    if not user.is_authenticated:
        return
    progress, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    if tab not in progress.tabs_seen:
        progress.tabs_seen = [*progress.tabs_seen, tab]
        progress.save(update_fields=["tabs_seen", "updated_at"])


def journey(user, programme):
    """Every lesson of a programme with where this learner stands on it:
    state is "done", "current" (open, not yet complete) or "locked"."""
    lessons = lessons_in_order(programme)
    needed_by_lesson = _tabs_with_content(lessons)
    seen = dict(LessonProgress.objects.filter(user=user, lesson__in=lessons).values_list("lesson_id", "tabs_seen"))
    activities = _activities_by_lesson(lessons)
    attempts = {}
    for attempt in LessonActivityAttempt.objects.filter(user=user, activity__lesson__in=lessons).order_by("created_at"):
        attempts.setdefault(attempt.activity_id, []).append(attempt)

    steps, open_so_far = [], True
    for number, lesson in enumerate(lessons, start=1):
        needed = needed_by_lesson.get(lesson.pk, [])
        done_tabs = [tab for tab in needed if tab in seen.get(lesson.pk, [])]
        tests = []
        for activity in activities.get(lesson.pk, []):
            tried = attempts.get(activity.pk, [])
            marked = [a for a in tried if a.status != a.STATUS_AWAITING]
            passed = any(a.passed for a in marked)
            sent = any(a.status == a.STATUS_AWAITING for a in tried)
            tests.append({
                "activity": activity, "tries": len(tried),
                "passed": passed, "sent": sent,
                # Recordings count once sent; everything else once passed.
                "done": passed or (activity.mode == "record" and sent),
                "best": max((a.percent for a in marked), default=None),
                "last": tried[-1] if tried else None,
            })
        # Opened at least once, and every part with something in it seen.
        finished = lesson.pk in seen and len(done_tabs) == len(needed)
        passed_all = all(test["done"] for test in tests)
        complete = finished and passed_all
        unlocked = open_so_far or user.is_staff
        steps.append({
            "lesson": lesson, "number": number,
            "state": "done" if (unlocked and complete) else ("current" if unlocked else "locked"),
            "unlocked": unlocked, "finished": finished, "complete": complete,
            "tabs": [{"slug": tab, "label": TAB_LABELS[tab], "seen": tab in done_tabs} for tab in needed],
            "tabs_left": len(needed) - len(done_tabs),
            "tests": tests, "tests_left": sum(1 for test in tests if not test["done"]),
            "passed": bool(tests) and passed_all,
        })
        open_so_far = open_so_far and complete
    for step, following in zip(steps, steps[1:] + [None]):
        step["next"] = following
    return steps


class Standing:
    """One learner's journey through one programme, read once per page."""

    def __init__(self, user, programme):
        self.steps = journey(user, programme)
        self.by_lesson = {step["lesson"].pk: step for step in self.steps}

    def step(self, lesson):
        return self.by_lesson.get(lesson.pk)

    def blocker(self, lesson):
        """The step that has to be completed first, or None if the lesson is open."""
        step = self.step(lesson)
        if step is None or step["unlocked"]:
            return None
        return next(s for s in self.steps[:step["number"] - 1] if not s["complete"])

    @property
    def done(self):
        return sum(1 for step in self.steps if step["state"] == "done")

    @property
    def current(self):
        return next((step for step in self.steps if step["state"] == "current"), None)
