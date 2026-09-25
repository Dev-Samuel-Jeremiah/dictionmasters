"""
Starting, timing, marking and finishing attempts.

Views stay thin: every rule that decides a score lives here, so a
practice check, a timed submission and a teacher's marks all arrive at a
result the same way.

The timer belongs to the server. A deadline is stamped when an attempt
starts; the countdown on the page is only a display, and anything saved
after the deadline (bar a few seconds' grace for a slow connection) is
ignored. Closing the tab doesn't stop the clock.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.echospell.marking import answers_match

from apps.manage.rich_text import sanitize_rich_text

from .models import LEVEL_ORDER, RUBRIC_CRITERIA, RUBRIC_MAX, Answer, Attempt, Question, grade_for

# A request posted as the clock runs out can take a moment to arrive.
GRACE = timedelta(seconds=15)
# Placement: the share of a level's questions you need right to count
# as having mastered that level.
MASTERY = 70


class AttemptNotAllowed(Exception):
    """Out of attempts — the message says why, for the learner."""


def attempts_used(user, assessment):
    return assessment.attempts.filter(user=user).exclude(status=Attempt.Status.IN_PROGRESS).count()


def attempts_left(user, assessment):
    """None when there is no limit."""
    if not assessment.max_attempts:
        return None
    return max(assessment.max_attempts - attempts_used(user, assessment), 0)


def open_attempt(user, assessment):
    return assessment.attempts.filter(user=user, status=Attempt.Status.IN_PROGRESS).first()


def start_or_resume(user, assessment):
    """The learner's attempt to work on: an unfinished one if they have
    it, otherwise a fresh one — within their attempt allowance."""
    current = open_attempt(user, assessment)
    if current:
        if is_expired(current):
            submit(current)
        else:
            return current

    if attempts_left(user, assessment) == 0:
        raise AttemptNotAllowed("You've used all your attempts at this assessment.")

    question_ids = list(assessment.questions.values_list("pk", flat=True))
    if assessment.shuffle_questions:
        random.shuffle(question_ids)

    attempt = Attempt.objects.create(
        user=user,
        assessment=assessment,
        question_order=question_ids,
    )
    if assessment.is_timed:
        attempt.deadline_at = attempt.started_at + timedelta(minutes=assessment.time_limit_minutes)
        attempt.save(update_fields=["deadline_at"])
    return attempt


def seconds_left(attempt):
    if not attempt.deadline_at:
        return None
    return max(int((attempt.deadline_at - timezone.now()).total_seconds()), 0)


def is_expired(attempt, grace=False):
    if not attempt.deadline_at:
        return False
    limit = attempt.deadline_at + (GRACE if grace else timedelta(0))
    return timezone.now() > limit


def option_order(attempt, question):
    """A question's options shuffled for this attempt — the same order
    every time the page loads, but a different order for each attempt,
    so answers can't be memorised by position."""
    options = question.option_list
    random.Random(f"{attempt.pk}:{question.pk}").shuffle(options)
    return options


def mark_objective(question, given):
    return answers_match(given, question.answer, transcription=question.type == Question.Type.TRANSCRIBE)


def record_answer(attempt, question, given="", recording=None):
    """Store what the learner gave, marking it straight away if a machine
    can. Speaking answers are left unmarked for a person."""
    answer, _ = Answer.objects.get_or_create(attempt=attempt, question=question)
    answer.given = str(given or "")[:2000]
    if recording:
        if answer.recording:
            answer.recording.delete(save=False)
        answer.recording = recording

    if question.is_objective:
        answer.is_correct = mark_objective(question, answer.given)
        answer.points_awarded = Decimal(question.points) if answer.is_correct else Decimal("0")
    else:
        answer.is_correct = None
        answer.points_awarded = None
    answer.save()
    return answer


def _recommend_level(attempt, answers_by_question):
    """Place the learner at the first level they haven't yet mastered.

    Each level's questions are scored on their own. Working up from the
    easiest, the first level below the mastery mark is where to start;
    someone who masters every level tested starts at the highest one.
    """
    by_level = {}
    for question in attempt.assessment.questions.exclude(level=""):
        answer = answers_by_question.get(question.pk)
        earned = answer.points_awarded if answer and answer.points_awarded is not None else Decimal("0")
        totals = by_level.setdefault(question.level, [Decimal("0"), Decimal("0")])
        totals[0] += earned
        totals[1] += question.points

    tested = [level for level in LEVEL_ORDER if level in by_level]
    for level in tested:
        earned, possible = by_level[level]
        if possible and earned * 100 / possible < MASTERY:
            return level
    return tested[-1] if tested else ""


def finalise(attempt):
    """Work out the score, grade and status from the answers held."""
    questions = attempt.ordered_questions()
    answers = {a.question_id: a for a in attempt.answers.all()}

    max_score = sum((Decimal(q.points) for q in questions), Decimal("0"))
    score = sum(
        (answers[q.pk].points_awarded for q in questions
         if q.pk in answers and answers[q.pk].points_awarded is not None),
        Decimal("0"),
    )
    waiting = any(
        not q.is_objective and (q.pk not in answers or answers[q.pk].points_awarded is None)
        for q in questions
    )

    attempt.score = score
    attempt.max_score = max_score
    attempt.percent = round(score * 100 / max_score) if max_score else 0
    attempt.grade = "" if waiting else grade_for(attempt.percent)
    attempt.passed = (not waiting) and attempt.percent >= attempt.assessment.pass_mark
    if attempt.assessment.kind == attempt.assessment.Kind.PLACEMENT and not waiting:
        attempt.recommended_level = _recommend_level(attempt, answers)

    if waiting:
        attempt.status = Attempt.Status.AWAITING
    elif attempt.marked_by_id:
        attempt.status = Attempt.Status.MARKED
    else:
        attempt.status = Attempt.Status.SUBMITTED
    attempt.save()
    return attempt


@transaction.atomic
def submit(attempt):
    """Close an attempt. Questions never answered are recorded as blank,
    so the review shows everything that was on the paper."""
    if not attempt.is_open:
        return attempt
    answered = set(attempt.answers.values_list("question_id", flat=True))
    for question in attempt.ordered_questions():
        if question.pk not in answered:
            record_answer(attempt, question, "")
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=["submitted_at"])
    return finalise(attempt)


@transaction.atomic
def apply_marks(attempt, marker, marks, feedback):
    """Record a teacher's rubric scores for the spoken answers.

    `marks` is {answer_id: {"sound": 4, ..., "comment": "..."}}. A
    spoken answer earns its question's points in proportion to its
    rubric total, so a perfect 25/25 earns full points.
    """
    for answer in attempt.answers.select_related("question"):
        if answer.question.is_objective or answer.pk not in marks:
            continue
        entry = marks[answer.pk]
        for field, _ in RUBRIC_CRITERIA:
            setattr(answer, field, entry.get(field))
        answer.comment = sanitize_rich_text(entry.get("comment", ""))[:2000]
        if answer.is_rubric_complete:
            total = sum(getattr(answer, field) for field, _ in RUBRIC_CRITERIA)
            answer.points_awarded = (
                Decimal(answer.question.points) * Decimal(total) / Decimal(RUBRIC_MAX)
            ).quantize(Decimal("0.01"))
        answer.save()

    attempt.feedback = sanitize_rich_text(feedback)[:4000]
    attempt.marked_by = marker
    attempt.marked_at = timezone.now()
    attempt.save(update_fields=["feedback", "marked_by", "marked_at"])
    return finalise(attempt)
