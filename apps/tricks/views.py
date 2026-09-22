"""
Tricks to Sound Fluent — a programme of its own, built on 44 Academy's
lessons. Each trick is a lesson with the same eight tabs, plus an
Assessment tab; the tricks are taken in order, each unlocking the next
(apps/tricks/progress.py).
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
from .models import TrickActivity, TrickActivityAttempt, TrickActivityResponse

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
    return book.lesson_detail(
        request, TRICKS, slug, tab, sound=trick,
        extra_tabs=[(ASSESSMENT, "Assessment")],
        extra={"step": step, "number": step["number"],
               "seen_tabs": [one["slug"] for one in step["tabs"] if one["seen"]]},
    )


@login_required
def sections(request, section=None):
    steps = {step["trick"].pk: step for step in progress.journey(request.user)}
    return book.lesson_sections(request, TRICKS, section, steps=steps)


# ---------------------------------------------------------------------------
# A trick's assessment activities, on EchoSpell's activity pages
# ---------------------------------------------------------------------------

def _open_activity(request, slug, activity_slug):
    """The trick and its activity, or where to send the learner instead:
    the trick has to be open to them, and every part of it opened."""
    trick = get_object_or_404(Sound.objects.in_programme(TRICKS), slug=slug, is_published=True)
    activity = get_object_or_404(TrickActivity, trick=trick, slug=activity_slug, is_published=True)
    if progress.locked_by(request.user, trick):
        return trick, activity, redirect("tricks:lesson", slug=trick.slug)
    step = progress.step_for(request.user, trick)
    if not step["finished"]:
        messages.info(request, "Open every part of the trick first, then take its assessment.")
        return trick, activity, redirect("tricks:lesson_tab", slug=trick.slug, tab=ASSESSMENT)
    return trick, activity, None


def _page(trick, number):
    """Breadcrumbs and way back, for EchoSpell's activity templates."""
    back = reverse("tricks:lesson_tab", args=[trick.slug, ASSESSMENT])
    return {
        "place": f"Trick {number} — Tricks to Sound Fluent",
        "crumbs": [{"url": reverse("tricks:home"), "label": "Tricks to Sound Fluent"},
                   {"url": reverse("tricks:lesson", args=[trick.slug]), "label": f"Trick {number}: {trick.name}"},
                   {"url": back, "label": "Assessment"}],
        "back_url": back, "back_label": "Back to the assessment",
    }


@login_required
def activity(request, slug, activity_slug):
    trick, activity, elsewhere = _open_activity(request, slug, activity_slug)
    if elsewhere:
        return elsewhere
    items = list(activity.items.all())

    if request.method == "POST" and items:
        attempt = TrickActivityAttempt.objects.create(user=request.user, activity=activity)
        is_recording = activity.mode == MODE_RECORD
        for item in items:
            given = request.POST.get(f"item-{item.id}", "").strip()[:1000]
            TrickActivityResponse.objects.create(
                attempt=attempt, item=item, given=given,
                is_correct=None if is_recording else mark_response(activity.kind_spec, item, given),
                recording=request.FILES.get(f"recording-{item.id}") or "",
            )
        attempt.recalculate()
        attempt.save()
        return redirect("tricks:activity_result", slug=trick.slug, activity_slug=activity.slug, attempt_id=attempt.pk)

    step = progress.step_for(request.user, trick)
    best = max(TrickActivityAttempt.objects.filter(user=request.user, activity=activity),
               key=lambda a: a.percent, default=None)
    return render(request, "echospell/activity_detail.html", {
        "activity": activity,
        "item_rows": _item_rows(activity, items),
        "buckets": activity.bucket_list,
        "previous": best,
        **_page(trick, step["number"]),
    })


@login_required
def activity_result(request, slug, activity_slug, attempt_id):
    trick = get_object_or_404(Sound.objects.in_programme(TRICKS), slug=slug)
    activity = get_object_or_404(TrickActivity, trick=trick, slug=activity_slug)
    attempt = get_object_or_404(TrickActivityAttempt, pk=attempt_id, activity=activity, user=request.user)
    kind = activity.kind_spec
    rows = [
        {"response": response, "item": response.item,
         "feedback": feedback_for(kind, response.item, response.given, response.is_correct)}
        for response in attempt.responses.select_related("item")
    ]
    step = progress.step_for(request.user, trick)
    return render(request, "echospell/activity_result.html", {
        "activity": activity, "attempt": attempt, "rows": rows,
        "retry_url": reverse("tricks:activity", args=[trick.slug, activity.slug]),
        "after_result": "tricks/_after_activity.html", "step": step, "trick": trick,
        **_page(trick, step["number"] if step else ""),
    })
