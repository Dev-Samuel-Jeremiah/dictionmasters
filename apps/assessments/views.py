"""
Views for assessments.

Learners: choose a type → pick an assessment → read the brief → take it
→ see the result. Teachers: a marking queue for their own school's
spoken answers. The correct answers never appear in a page a learner can
view source on until that question has been answered and locked.
"""

import json

from apps.accounts.access import limit_to_levels, require_level

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.book.views import PHONEMIC_CHART
from apps.echospell.models import Level

from . import scoring
from .models import RUBRIC_CRITERIA, Assessment, Attempt, Question

KIND_INFO = {
    Assessment.Kind.PRACTICE: {
        "icon": "✏️",
        "blurb": "Learn as you go. Check each answer the moment you give it and see why.",
        "points": ["No timer", "Feedback after every question", "Try as often as you like"],
    },
    Assessment.Kind.TIMED: {
        "icon": "⏱️",
        "blurb": "Show what you know against the clock, the way an exam feels.",
        "points": ["A countdown timer", "Answers saved as you go", "Results when you finish"],
    },
    Assessment.Kind.SPEAKING: {
        "icon": "🎙️",
        "blurb": "Read and speak aloud. Your teacher listens and marks your pronunciation.",
        "points": ["Record your voice", "Marked by your teacher", "Scored on sounds, stress, pace and more"],
    },
    Assessment.Kind.PLACEMENT: {
        "icon": "🧭",
        "blurb": "Questions from easy to hard that find the right EchoSpell level for you.",
        "points": ["Questions across the levels", "Recommends where to start", "Takes about ten minutes"],
    },
}

IPA_KEYS = [symbol for group in PHONEMIC_CHART for _, symbol, _ in group["sounds"]] + ["ˈ", "ˌ", "/"]


# ---------------------------------------------------------------------------
# Who may see and mark what
# ---------------------------------------------------------------------------

def _own_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("assessment"), pk=attempt_id)
    if attempt.user_id != request.user.pk:
        raise Http404
    return attempt


def can_mark(user, attempt):
    """Staff mark anyone. A teacher marks students at their own school —
    individual learners have no school, so their work goes to staff."""
    if user.is_staff:
        return True
    return bool(
        user.is_teacher and user.school_id
        and attempt.user.school_id == user.school_id
        and attempt.user.is_student
    )


def markable(user):
    waiting = Attempt.objects.filter(status=Attempt.Status.AWAITING)
    if user.is_staff:
        return waiting
    if user.is_teacher and user.school_id:
        return waiting.filter(user__school=user.school, user__role="student")
    return waiting.none()


def _can_use_marking(user):
    return user.is_staff or (user.is_teacher and user.school_id)


# ---------------------------------------------------------------------------
# Choosing
# ---------------------------------------------------------------------------

@login_required
def hub(request):
    counts = dict(
        limit_to_levels(Assessment.objects.filter(is_published=True), request.user)
        .values_list("kind").annotate(n=Count("pk")).values_list("kind", "n")
    )
    kinds = [
        {"value": value, "label": label, "count": counts.get(value, 0), **KIND_INFO[value]}
        for value, label in Assessment.Kind.choices
    ]
    return render(request, "assessments/hub.html", {
        "kinds": kinds,
        "recent": Attempt.objects.filter(user=request.user).exclude(status=Attempt.Status.IN_PROGRESS)
                  .select_related("assessment")[:3],
        "in_progress": Attempt.objects.filter(user=request.user, status=Attempt.Status.IN_PROGRESS)
                       .select_related("assessment"),
        "can_mark": _can_use_marking(request.user),
        "to_mark": markable(request.user).count() if _can_use_marking(request.user) else 0,
    })


@login_required
def kind_list(request, kind):
    if kind not in Assessment.Kind.values:
        raise Http404
    assessments = limit_to_levels(
        Assessment.objects.filter(is_published=True, kind=kind), request.user
    ).annotate(question_count=Count("questions"))
    mine = (
        Attempt.objects.filter(user=request.user, assessment__in=assessments)
        .exclude(status=Attempt.Status.IN_PROGRESS)
        .values("assessment").annotate(best=Max("percent"), taken=Count("pk"))
    )
    stats = {row["assessment"]: row for row in mine}
    open_ids = set(
        Attempt.objects.filter(user=request.user, status=Attempt.Status.IN_PROGRESS)
        .values_list("assessment_id", flat=True)
    )
    rows = []
    for assessment in assessments:
        taken = stats.get(assessment.pk, {}).get("taken", 0)
        left = assessment.max_attempts - taken if assessment.max_attempts else None
        rows.append({
            "assessment": assessment,
            "best": stats.get(assessment.pk, {}).get("best"),
            "taken": taken,
            "left": left,
            "in_progress": assessment.pk in open_ids,
        })
    return render(request, "assessments/kind_list.html", {
        "kind": kind,
        "kind_label": Assessment.Kind(kind).label,
        "info": KIND_INFO[kind],
        "rows": rows,
    })


@login_required
def detail(request, slug):
    assessment = get_object_or_404(Assessment, slug=slug, is_published=True)
    require_level(request.user, assessment.level)
    return render(request, "assessments/detail.html", {
        "assessment": assessment,
        "info": KIND_INFO[assessment.kind],
        "question_count": assessment.questions.count(),
        "left": scoring.attempts_left(request.user, assessment),
        "used": scoring.attempts_used(request.user, assessment),
        "resumable": scoring.open_attempt(request.user, assessment),
    })


@login_required
@require_POST
def start(request, slug):
    assessment = get_object_or_404(Assessment, slug=slug, is_published=True)
    require_level(request.user, assessment.level)
    if not assessment.questions.exists():
        messages.error(request, "This assessment has no questions yet.")
        return redirect("assessments:detail", slug=slug)
    try:
        attempt = scoring.start_or_resume(request.user, assessment)
    except scoring.AttemptNotAllowed as reason:
        messages.error(request, str(reason))
        return redirect("assessments:detail", slug=slug)
    if not attempt.is_open:
        return redirect("assessments:result", attempt_id=attempt.pk)
    return redirect("assessments:take", attempt_id=attempt.pk)


# ---------------------------------------------------------------------------
# Taking
# ---------------------------------------------------------------------------

@login_required
def take(request, attempt_id):
    attempt = _own_attempt(request, attempt_id)
    if not attempt.is_open:
        return redirect("assessments:result", attempt_id=attempt.pk)
    if scoring.is_expired(attempt, grace=True):
        scoring.submit(attempt)
        messages.info(request, "Time ran out — your answers were submitted.")
        return redirect("assessments:result", attempt_id=attempt.pk)

    questions = attempt.ordered_questions()
    answers = {a.question_id: a for a in attempt.answers.all()}

    if request.method == "POST":
        in_time = not scoring.is_expired(attempt, grace=True)
        for question in questions:
            existing = answers.get(question.pk)
            if existing and existing.checked_at:
                continue  # a checked practice answer is locked
            if not in_time:
                continue  # after the deadline only what was saved in time counts
            # The form carries every answer, so what's posted is the final
            # word — including an answer the learner deliberately cleared.
            scoring.record_answer(
                attempt, question,
                request.POST.get(f"q-{question.pk}", ""),
                request.FILES.get(f"recording-{question.pk}"),
            )
        scoring.submit(attempt)
        return redirect("assessments:result", attempt_id=attempt.pk)

    rows = []
    for number, question in enumerate(questions, start=1):
        answer = answers.get(question.pk)
        rows.append({
            "number": number,
            "question": question,
            "options": scoring.option_order(attempt, question) if question.type in Question.CHOICE_TYPES else [],
            "given": answer.given if answer else "",
            "checked": bool(answer and answer.checked_at),
            "is_correct": answer.is_correct if answer and answer.checked_at else None,
            "correct_answer": question.first_answer if answer and answer.checked_at else "",
            "explanation": question.explanation if answer and answer.checked_at else "",
        })

    return render(request, "assessments/take.html", {
        "attempt": attempt,
        "assessment": attempt.assessment,
        "rows": rows,
        "seconds_left": scoring.seconds_left(attempt),
        "ipa_keys": IPA_KEYS,
        "has_speaking": any(r["question"].type == Question.Type.SPEAK for r in rows),
    })


def _question_for(attempt, request):
    try:
        payload = json.loads(request.body)
        question_id = int(payload["question"])
    except (ValueError, KeyError, TypeError):
        return None, None
    question = attempt.assessment.questions.filter(pk=question_id).first()
    return question, str(payload.get("given", ""))[:2000]


@login_required
@require_POST
def save_answer(request, attempt_id):
    """Autosave one answer. Deliberately says nothing about whether it
    is right — that would give a timed test away."""
    attempt = _own_attempt(request, attempt_id)
    if not attempt.is_open or scoring.is_expired(attempt, grace=True):
        return JsonResponse({"saved": False, "expired": True}, status=409)
    question, given = _question_for(attempt, request)
    if question is None or not question.is_objective:
        return JsonResponse({"saved": False}, status=400)
    existing = attempt.answers.filter(question=question).first()
    if existing and existing.checked_at:
        return JsonResponse({"saved": False, "locked": True}, status=409)
    scoring.record_answer(attempt, question, given)
    return JsonResponse({"saved": True, "seconds_left": scoring.seconds_left(attempt)})


@login_required
@require_POST
def check_answer(request, attempt_id):
    """Practice quizzes only: mark one answer now, lock it, and explain."""
    attempt = _own_attempt(request, attempt_id)
    if not attempt.is_open or not attempt.assessment.is_practice:
        return JsonResponse({"error": "Checking isn't available here."}, status=400)
    question, given = _question_for(attempt, request)
    if question is None or not question.is_objective:
        return JsonResponse({"error": "Unknown question."}, status=400)

    answer = attempt.answers.filter(question=question).first()
    if not (answer and answer.checked_at):
        if not given.strip():
            return JsonResponse({"error": "Give an answer before checking."}, status=400)
        answer = scoring.record_answer(attempt, question, given)
        answer.checked_at = timezone.now()
        answer.save(update_fields=["checked_at"])

    return JsonResponse({
        "correct": answer.is_correct,
        "answer": question.first_answer,
        "explanation": question.explanation,
    })


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@login_required
def result(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("assessment", "user", "marked_by"), pk=attempt_id)
    if attempt.user_id != request.user.pk and not can_mark(request.user, attempt):
        raise Http404
    if attempt.is_open:
        return redirect("assessments:take", attempt_id=attempt.pk)

    answers = {a.question_id: a for a in attempt.answers.all()}
    rows = [
        {"number": n, "question": q, "answer": answers.get(q.pk)}
        for n, q in enumerate(attempt.ordered_questions(), start=1)
    ]
    placement_level = None
    if attempt.recommended_level:
        placement_level = Level.objects.filter(name=attempt.recommended_level, is_published=True).first()

    return render(request, "assessments/result.html", {
        "attempt": attempt,
        "assessment": attempt.assessment,
        "rows": rows,
        "placement_level": placement_level,
        "left": scoring.attempts_left(attempt.user, attempt.assessment),
    })


@login_required
def my_results(request):
    attempts = Attempt.objects.filter(user=request.user).select_related("assessment")
    return render(request, "assessments/my_results.html", {
        "in_progress": [a for a in attempts if a.is_open],
        "finished": [a for a in attempts if not a.is_open],
    })


# ---------------------------------------------------------------------------
# Marking
# ---------------------------------------------------------------------------

@login_required
def marking_queue(request):
    if not _can_use_marking(request.user):
        raise PermissionDenied
    return render(request, "assessments/marking_queue.html", {
        "waiting": markable(request.user).select_related("assessment", "user").order_by("submitted_at"),
        "recent": Attempt.objects.filter(marked_by=request.user).select_related("assessment", "user")
                  .order_by("-marked_at")[:10],
    })


@login_required
def mark(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("assessment", "user"), pk=attempt_id)
    if not can_mark(request.user, attempt):
        raise PermissionDenied
    if attempt.is_open:
        messages.error(request, "That attempt hasn't been submitted yet.")
        return redirect("assessments:marking_queue")

    spoken = [a for a in attempt.answers.select_related("question") if not a.question.is_objective]
    spoken.sort(key=lambda a: attempt.question_order.index(a.question_id) if a.question_id in attempt.question_order else 0)
    errors = []

    if request.method == "POST":
        marks = {}
        for answer in spoken:
            entry = {"comment": request.POST.get(f"{answer.pk}-comment", "")}
            for field, label in RUBRIC_CRITERIA:
                raw = request.POST.get(f"{answer.pk}-{field}", "")
                if raw not in {"1", "2", "3", "4", "5"}:
                    errors.append(f"Question {answer.question.prompt[:40]!r}: score “{label}” from 1 to 5.")
                    entry[field] = None
                else:
                    entry[field] = int(raw)
            marks[answer.pk] = entry
        if not errors:
            scoring.apply_marks(attempt, request.user, marks, request.POST.get("feedback", ""))
            messages.success(request, f"Marks saved — {attempt.user.get_full_name() or attempt.user.email} can now see their result.")
            return redirect("assessments:marking_queue")

    posted = request.POST if request.method == "POST" else {}
    spoken_rows = [
        {
            "answer": answer,
            "scores": [
                {
                    "field": field,
                    "label": label,
                    "value": str(posted.get(f"{answer.pk}-{field}", getattr(answer, field) or "")),
                }
                for field, label in RUBRIC_CRITERIA
            ],
            "comment": posted.get(f"{answer.pk}-comment", answer.comment),
        }
        for answer in spoken
    ]
    return render(request, "assessments/mark.html", {
        "attempt": attempt,
        "assessment": attempt.assessment,
        "spoken_rows": spoken_rows,
        "objective": [a for a in attempt.answers.select_related("question") if a.question.is_objective],
        "scale": ["1", "2", "3", "4", "5"],
        "errors": errors,
        "feedback": posted.get("feedback", attempt.feedback),
    })
