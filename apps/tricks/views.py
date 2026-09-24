"""
Tricks to Sound Fluent — a programme of its own, built on 44 Academy's
lessons. Each trick is a lesson with the same eight tabs, plus an
Assessment tab.

The lesson pages taken in order live here too, for both programmes:
opening a lesson (locked until the one before it is complete), its
Assessment tab, and its assessment activities on EchoSpell's activity
pages (apps/tricks/progress.py has the rules). 44 Academy's views call
these with its own programme.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.book import views as book
from apps.book.models import TRICKS, Sound
from apps.book.programmes import programme_for
from apps.echospell.activity_kinds import MODE_RECORD
from apps.echospell.marking import feedback_for, mark_response
from apps.echospell.views import _item_rows

from . import progress
from .models import LessonActivity, LessonActivityAttempt, LessonActivityResponse

ASSESSMENT = "assessment"


# ---------------------------------------------------------------------------
# Lessons taken in order, for either programme
# ---------------------------------------------------------------------------

def open_lesson(request, programme, slug, tab="lens"):
    """One lesson and its tabs, or the page saying what to finish first."""
    info = programme_for(programme)
    lesson = get_object_or_404(Sound.objects.in_programme(programme).select_related("category"),
                               slug=slug, is_published=True)
    if tab not in progress.TAB_CONTENT and tab != ASSESSMENT:
        raise Http404("That tab doesn't exist.")
    standing = progress.Standing(request.user, programme)
    blocker = standing.blocker(lesson)
    if blocker:
        return render(request, "tricks/locked.html", {
            "programme": info, "lesson": lesson, "blocker": blocker, "step": standing.step(lesson),
        }, status=403)
    step = standing.step(lesson)
    if info["numbered"] and tab in progress.TAB_CONTENT:
        populated = [one["slug"] for one in step["tabs"]]
        if tab not in populated and populated:
            return redirect(info["lesson_tab"], slug=lesson.slug, tab=populated[0])
    progress.record_tab(request.user, lesson, tab)
    step = progress.Standing(request.user, programme).step(lesson)
    return book.lesson_detail(
        request, programme, slug, tab, sound=lesson,
        extra_tabs=[(ASSESSMENT, "Assessment")],
        # Tricks are called by number (Trick 3); a sound keeps its group's name.
        extra={"step": step, "number": step["number"] if info["numbered"] else None,
               "seen_tabs": [one["slug"] for one in step["tabs"] if one["seen"]]},
    )


def _open_activity(request, programme, slug, activity_slug):
    """The lesson and its activity, or where to send the learner instead:
    the lesson has to be open to them, and every part of it opened."""
    info = programme_for(programme)
    lesson = get_object_or_404(Sound.objects.in_programme(programme), slug=slug, is_published=True)
    activity = get_object_or_404(LessonActivity, lesson=lesson, slug=activity_slug, is_published=True)
    standing = progress.Standing(request.user, programme)
    if standing.blocker(lesson):
        return lesson, activity, standing, redirect(info["lesson"], slug=lesson.slug)
    if not standing.step(lesson)["finished"]:
        messages.info(request, f"Open every part of the {info['lesson_word']} first, then take its assessment.")
        return lesson, activity, standing, redirect(info["lesson_tab"], slug=lesson.slug, tab=ASSESSMENT)
    return lesson, activity, standing, None


def _page(programme, lesson, number):
    """Breadcrumbs and the way back, for EchoSpell's activity templates."""
    info = programme_for(programme)
    word = info["lesson_word"].capitalize()
    back = reverse(info["lesson_tab"], args=[lesson.slug, ASSESSMENT])
    return {
        "programme": info,
        "place": f"{word} {number} — {info['name']}",
        "crumbs": [{"url": reverse(info["home"]), "label": info["name"]},
                   {"url": reverse(info["lesson"], args=[lesson.slug]), "label": f"{word} {number}: {lesson.name}"},
                   {"url": back, "label": "Assessment"}],
        "back_url": back, "back_label": "Back to the assessment",
    }


def take_activity(request, programme, slug, activity_slug):
    lesson, activity, standing, elsewhere = _open_activity(request, programme, slug, activity_slug)
    if elsewhere:
        return elsewhere
    items = list(activity.items.all())

    if request.method == "POST" and items:
        attempt = LessonActivityAttempt.objects.create(user=request.user, activity=activity)
        is_recording = activity.mode == MODE_RECORD
        for item in items:
            given = request.POST.get(f"item-{item.id}", "").strip()[:1000]
            LessonActivityResponse.objects.create(
                attempt=attempt, item=item, given=given,
                is_correct=None if is_recording else mark_response(activity.kind_spec, item, given),
                recording=request.FILES.get(f"recording-{item.id}") or "",
            )
        attempt.recalculate()
        attempt.save()
        return redirect(programme_for(programme)["activity_result"],
                        slug=lesson.slug, activity_slug=activity.slug, attempt_id=attempt.pk)

    best = max(LessonActivityAttempt.objects.filter(user=request.user, activity=activity),
               key=lambda a: a.percent, default=None)
    return render(request, "echospell/activity_detail.html", {
        "activity": activity,
        "item_rows": _item_rows(activity, items),
        "buckets": activity.bucket_list,
        "previous": best,
        **_page(programme, lesson, standing.step(lesson)["number"]),
    })


def activity_result(request, programme, slug, activity_slug, attempt_id):
    info = programme_for(programme)
    lesson = get_object_or_404(Sound.objects.in_programme(programme), slug=slug)
    activity = get_object_or_404(LessonActivity, lesson=lesson, slug=activity_slug)
    attempt = get_object_or_404(LessonActivityAttempt, pk=attempt_id, activity=activity, user=request.user)
    kind = activity.kind_spec
    rows = []
    for response in attempt.responses.select_related("item"):
        teacher_mark = response.awarded_mark
        rows.append({
            "response": response, "item": response.item,
            "teacher_mark": teacher_mark,
            "teacher_passed": (teacher_mark is not None
                               and teacher_mark * 100 >= activity.pass_mark * 5),
            "feedback": (f"Your teacher awarded {teacher_mark} out of 5 marks."
                         if teacher_mark is not None
                         else feedback_for(kind, response.item, response.given, response.is_correct)),
        })
    step = progress.Standing(request.user, programme).step(lesson)
    return render(request, "echospell/activity_result.html", {
        "activity": activity, "attempt": attempt, "rows": rows,
        "uses_numeric_marks": any(row["teacher_mark"] is not None for row in rows),
        "retry_url": reverse(info["activity"], args=[lesson.slug, activity.slug]),
        "after_result": "tricks/_after_activity.html", "step": step, "lesson": lesson,
        **_page(programme, lesson, step["number"] if step else ""),
    })


# ---------------------------------------------------------------------------
# Tricks to Sound Fluent's own pages
# ---------------------------------------------------------------------------

@login_required
def home(request):
    standing = progress.Standing(request.user, TRICKS)
    return render(request, "tricks/home.html", {
        "programme": programme_for(TRICKS),
        "total_tricks": len(standing.steps),
        "done": standing.done,
        "current": standing.current,
        "sections": book.TABS,
    })


@login_required
def lessons(request):
    return render(request, "book/academy.html", {
        "programme": programme_for(TRICKS),
        "steps": progress.Standing(request.user, TRICKS).steps,
    })


@login_required
def lesson(request, slug, tab="lens"):
    return open_lesson(request, TRICKS, slug, tab)


@login_required
def sections(request, section=None):
    return book.lesson_sections(request, TRICKS, section, steps=progress.Standing(request.user, TRICKS).by_lesson)


@login_required
def activity(request, slug, activity_slug):
    return take_activity(request, TRICKS, slug, activity_slug)


@login_required
def activity_result_page(request, slug, activity_slug, attempt_id):
    return activity_result(request, TRICKS, slug, activity_slug, attempt_id)
