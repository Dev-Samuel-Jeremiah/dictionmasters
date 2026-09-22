"""
Every learner's results in one place, and marking for anything a person
has to judge.

Three kinds of attempt are graded on the site:

  assessment  an Assessments test (apps/assessments). Spoken answers are
              marked on the five-point rubric, by the same rules as the
              teachers' marking page (scoring.apply_marks).
  echospell   an EchoSpell activity (apps/echospell).
  lesson      an assessment activity of a 44 Academy sound or a trick (apps/tricks).

For the two activity kinds, recordings are marked Good or Needs work;
the score, pass and the "reviewed by the teacher" status follow from
that, and the learner sees it with the feedback on their result page.
"""

from django.db.models import Q

from apps.assessments import scoring
from apps.assessments.models import RUBRIC_CRITERIA, Attempt
from apps.book.models import TRICKS
from apps.echospell.marking import feedback_for
from apps.echospell.models import ActivityAttempt
from apps.tricks.models import LessonActivityAttempt

# Each source, as the results pages need it.
SOURCES = {
    "assessment": {
        "label": "Assessments", "icon": "📋",
        "rows": lambda: Attempt.objects.exclude(status=Attempt.Status.IN_PROGRESS)
                        .select_related("assessment", "user"),
        "waiting": Q(status=Attempt.Status.AWAITING),
        "search": ["user__email", "user__first_name", "user__last_name", "assessment__title"],
    },
    "echospell": {
        "label": "EchoSpell", "icon": "🔊",
        "rows": lambda: ActivityAttempt.objects.select_related("activity__group__level", "user"),
        "waiting": Q(status=ActivityAttempt.STATUS_AWAITING),
        "search": ["user__email", "user__first_name", "user__last_name", "activity__title"],
    },
    "lesson": {
        "label": "44 Academy & Tricks", "icon": "✨",
        "rows": lambda: LessonActivityAttempt.objects.select_related("activity__lesson__category", "user"),
        "waiting": Q(status=LessonActivityAttempt.STATUS_AWAITING),
        "search": ["user__email", "user__first_name", "user__last_name", "activity__title", "activity__lesson__name"],
    },
}

# How many of each source a list page reads back, newest first.
LIST_LIMIT = 400


def learner_name(user):
    return user.get_full_name() or user.email


def to_mark_count():
    return sum(source["rows"]().filter(source["waiting"]).count() for source in SOURCES.values())


def summarise(source, attempt):
    """One attempt as a row of the results list."""
    if source == "assessment":
        waiting = attempt.status == Attempt.Status.AWAITING
        return {
            "source": source, "pk": attempt.pk, "learner": learner_name(attempt.user),
            "email": attempt.user.email, "what": attempt.assessment.title,
            "type": attempt.assessment.get_kind_display(), "where": "Assessments",
            "when": attempt.submitted_at or attempt.started_at, "waiting": waiting,
            "status": attempt.get_status_display(), "percent": None if waiting else attempt.percent,
            "passed": attempt.passed,
        }
    activity = attempt.activity
    if source == "echospell":
        where = f"EchoSpell · {activity.group.level.name} · Group {activity.group.number}"
    else:
        lesson = activity.lesson
        where = f"{'Tricks' if lesson.programme == TRICKS else '44 Academy'} · {lesson.name}"
    waiting = attempt.status == attempt.STATUS_AWAITING
    return {
        "source": source, "pk": attempt.pk, "learner": learner_name(attempt.user),
        "email": attempt.user.email, "what": activity.title, "type": activity.kind_label, "where": where,
        "when": attempt.created_at, "waiting": waiting, "status": attempt.get_status_display(),
        "percent": None if waiting else attempt.percent, "passed": attempt.passed,
    }


def rows(show="all", source=None, query=""):
    """Results from one source or all of them, newest first."""
    found = []
    for key, spec in SOURCES.items():
        if source and key != source:
            continue
        queryset = spec["rows"]()
        if show == "to-mark":
            queryset = queryset.filter(spec["waiting"])
        if query:
            condition = Q()
            for field in spec["search"]:
                condition |= Q(**{f"{field}__icontains": query})
            queryset = queryset.filter(condition)
        order = "-submitted_at" if key == "assessment" else "-created_at"
        found += [summarise(key, attempt) for attempt in queryset.order_by(order)[:LIST_LIMIT]]
    # Waiting work oldest first, so nobody is left longest; results newest first.
    if show == "to-mark":
        return sorted(found, key=lambda row: row["when"])
    return sorted(found, key=lambda row: row["when"], reverse=True)


def get_attempt(source, pk):
    spec = SOURCES.get(source)
    if spec is None:
        return None
    return spec["rows"]().filter(pk=pk).first()


# ---------------------------------------------------------------------------
# One attempt: what the learner gave, and marking it
# ---------------------------------------------------------------------------

def activity_answers(attempt):
    kind = attempt.activity.kind_spec
    return [
        {"response": response, "item": response.item,
         "is_recording": bool(response.recording) or attempt.activity.mode == "record",
         "feedback": feedback_for(kind, response.item, response.given, response.is_correct)}
        for response in attempt.responses.select_related("item")
    ]


def mark_activity(attempt, verdicts, feedback):
    """A teacher's marks for an activity attempt's recordings.

    `verdicts` is {response_id: True (Good) / False (Needs work)}. Every
    recording must have one; returns the ids still missing, if any.
    """
    responses = list(attempt.responses.all())
    recordings = [r for r in responses if r.recording or attempt.activity.mode == "record"]
    missing = [r.pk for r in recordings if r.pk not in verdicts]
    if missing:
        return missing
    for response in recordings:
        response.is_correct = verdicts[response.pk]
        response.save(update_fields=["is_correct"])
    attempt.recalculate()
    attempt.status = attempt.STATUS_REVIEWED
    attempt.teacher_score = attempt.percent
    attempt.teacher_feedback = str(feedback or "")[:4000]
    attempt.save()
    return []


def assessment_answers(attempt):
    """Each answer in paper order; spoken ones with their rubric scores."""
    answers = {a.question_id: a for a in attempt.answers.select_related("question")}
    shown = []
    for number, question in enumerate(attempt.ordered_questions(), start=1):
        answer = answers.get(question.pk)
        shown.append({
            "number": number, "question": question, "answer": answer,
            "spoken": not question.is_objective,
            "scores": [{"field": field, "label": label, "value": str(getattr(answer, field) or "") if answer else ""}
                       for field, label in RUBRIC_CRITERIA],
        })
    return shown


def mark_assessment(attempt, marker, post):
    """Rubric scores from the posted form. Returns the problems, if any."""
    marks, errors = {}, []
    for answer in attempt.answers.select_related("question"):
        if answer.question.is_objective:
            continue
        entry = {"comment": post.get(f"{answer.pk}-comment", "")}
        for field, label in RUBRIC_CRITERIA:
            raw = post.get(f"{answer.pk}-{field}", "")
            if raw not in {"1", "2", "3", "4", "5"}:
                errors.append(f"“{answer.question.prompt[:40]}”: give “{label}” a score from 1 to 5.")
            else:
                entry[field] = int(raw)
        marks[answer.pk] = entry
    if not errors:
        scoring.apply_marks(attempt, marker, marks, post.get("feedback", ""))
    return errors
