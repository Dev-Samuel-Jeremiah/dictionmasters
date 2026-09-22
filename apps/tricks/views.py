"""
Tricks to Sound Fluent — a programme of its own, built on 44 Academy's
lessons. Each trick is a lesson with the same eight tabs, plus an
Assessment tab; the tricks are taken in order, each unlocking the next
(apps/tricks/progress.py).
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from apps.assessments import scoring
from apps.book import views as book
from apps.book.models import TRICKS, Sound
from apps.book.programmes import programme_for

from . import progress

ASSESSMENT = "assessment"


@login_required
def home(request):
    steps = progress.journey(request.user)
    return render(request, "tricks/home.html", {
        "programme": programme_for(TRICKS),
        "total_tricks": len(steps),
        "done": sum(1 for step in steps if step["state"] == "done"),
        "current": next((step for step in steps if step["state"] == "current"), None),
        "sections": book.TABS,
    })


@login_required
def lessons(request):
    return render(request, "book/academy.html", {
        "programme": programme_for(TRICKS),
        "steps": progress.journey(request.user),
    })


@login_required
def lesson(request, slug, tab="lens"):
    trick = get_object_or_404(Sound.objects.in_programme(TRICKS).select_related("category"),
                              slug=slug, is_published=True)
    blocker = progress.locked_by(request.user, trick)
    if blocker:
        return render(request, "tricks/locked.html", {
            "programme": programme_for(TRICKS), "trick": trick, "blocker": blocker,
            "step": progress.step_for(request.user, trick),
        }, status=403)
    if tab not in progress.TAB_CONTENT and tab != ASSESSMENT:
        raise Http404("That tab doesn't exist.")
    progress.record_tab(request.user, trick, tab)
    step = progress.step_for(request.user, trick)
    test = {}
    if tab == ASSESSMENT and step["assessment"]:
        assessment = step["assessment"]
        test = {
            "question_count": assessment.questions.count(),
            "open_attempt": scoring.open_attempt(request.user, assessment),
            "attempts_left": scoring.attempts_left(request.user, assessment),
        }
    return book.lesson_detail(
        request, TRICKS, slug, tab, sound=trick,
        extra_tabs=[(ASSESSMENT, "Assessment")],
        extra={"step": step, "number": step["number"],
               "seen_tabs": [one["slug"] for one in step["tabs"] if one["seen"]], **test},
    )


@login_required
def sections(request, section=None):
    steps = {step["trick"].pk: step for step in progress.journey(request.user)}
    return book.lesson_sections(request, TRICKS, section, steps=steps)
