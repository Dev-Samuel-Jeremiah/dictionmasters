"""
A term's results, for report cards.

    term_results(pupils, dated)       a row per pupil: CA 1, CA 2 and exam
                                      scores, the weighted total and grade,
                                      days practised, and their card
    save_comments(teacher, ...)       the teacher's comments, kept on the
                                      (still unpublished) cards
    publish(admin, rows, dated)       freeze every unpublished card as it is

Scores come from the CA tests and exams for the pupil's level and the
term's number (apps/assessments), sat between the term's first day and
three weeks after its last (time for spoken answers to be marked). A test
waiting to be marked shows as pending; one not sat counts as 0 in the
total, which is what most schools do. A published card keeps the numbers
it had when it was published, whatever happens after.

Everything is gathered for the whole class at once — a fixed number of
queries, never one per pupil.
"""

from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.assessments.models import Assessment, Attempt
from apps.clash.models import Match
from apps.echospell.models import ActivityAttempt, GroupProgress
from apps.learning_modules.models import DayProgress
from apps.tutor.models import TutorSession

from .calendar import term_window
from .models import Grading, ReportCard

SLOTS = ("ca1", "ca2", "exam")


def _days_practised(ids, dated):
    """{pupil id: days in the term with any practice}. One query per tool."""
    tz = timezone.get_current_timezone()
    sources = [
        (ActivityAttempt.objects.filter(user__in=ids), "created_at"),
        (GroupProgress.objects.filter(user__in=ids), "completed_at"),
        (DayProgress.objects.filter(user__in=ids), "completed_at"),
        (Attempt.objects.filter(user__in=ids).exclude(submitted_at=None), "submitted_at"),
        (Match.objects.filter(user__in=ids, status=Match.Status.FINISHED).exclude(finished_at=None), "finished_at"),
        (TutorSession.objects.filter(user__in=ids, status=TutorSession.STATUS_DONE), "finished_at"),
    ]
    days = {}
    for queryset, field in sources:
        # "on_day", not "day": a module DayProgress has a field called day.
        rows = (queryset.annotate(on_day=TruncDate(field, tzinfo=tz))
                .filter(on_day__gte=dated.starts, on_day__lte=dated.ends)
                .values_list("user", "on_day").distinct())
        for user, day in rows:
            days.setdefault(user, set()).add(day)
    return {user: len(found) for user, found in days.items()}


def term_results(pupils, dated):
    grading = Grading.load()
    pupils = list(pupils.order_by("first_name", "last_name", "pk")) if hasattr(pupils, "order_by") else list(pupils)
    ids = [p.pk for p in pupils]
    start, end = term_window(dated)

    tests = Assessment.objects.filter(kind__in=[Assessment.Kind.CA, Assessment.Kind.EXAM], term=dated.number)
    scores = {}           # (pupil, level, slot) -> percent, or "pending"
    for attempt in (Attempt.objects.filter(user__in=ids, assessment__in=tests, submitted_at__range=(start, end))
                    .exclude(status=Attempt.Status.IN_PROGRESS).select_related("assessment")):
        key = (attempt.user_id, attempt.assessment.level, attempt.assessment.slot)
        value = "pending" if attempt.status == Attempt.Status.AWAITING else attempt.percent
        if scores.get(key) in (None, "pending"):
            scores[key] = value
    cards = {c.student_id: c for c in ReportCard.objects.filter(student__in=ids, term=dated.term)}
    days = _days_practised(ids, dated)

    rows = []
    for pupil in pupils:
        card = cards.get(pupil.pk)
        if card and card.published_at:
            row = {slot: getattr(card, slot) for slot in SLOTS}
            row.update(total=card.total, grade=card.grade, days=card.days_practised, pending=[], missing=[])
        else:
            found = {slot: scores.get((pupil.pk, pupil.level, slot)) for slot in SLOTS}
            pending = [slot for slot, value in found.items() if value == "pending"]
            missing = [slot for slot, value in found.items() if value is None]
            marks = {slot: value if isinstance(value, int) else None for slot, value in found.items()}
            weights = {"ca1": grading.ca1_weight, "ca2": grading.ca2_weight, "exam": grading.exam_weight}
            total = round(sum((marks[slot] or 0) * weights[slot] for slot in SLOTS) / 100)
            row = {**marks, "total": total, "grade": grading.grade(total), "days": days.get(pupil.pk, 0),
                   "pending": pending, "missing": missing}
        rows.append({"pupil": pupil, "card": card, "published": bool(card and card.published_at), **row})
    return rows


def save_comments(teacher, rows, dated, comments):
    """Keep each pupil's comment (`comments`: {pupil id: text}) on their
    card, made if it isn't there yet. Published cards are left as they are."""
    new, changed = [], []
    for row in rows:
        text = comments.get(row["pupil"].pk)
        if text is None or row["published"]:
            continue
        text = text.strip()[:2000]
        card = row["card"]
        if card is None:
            new.append(ReportCard(student=row["pupil"], term=dated.term, level=row["pupil"].level,
                                  teacher_comment=text, comment_by=teacher))
        elif card.teacher_comment != text:
            card.teacher_comment, card.comment_by = text, teacher
            changed.append(card)
    ReportCard.objects.bulk_create(new)
    ReportCard.objects.bulk_update(changed, ["teacher_comment", "comment_by"])
    return len(new) + len(changed)


def publish(admin, rows, dated):
    """Freeze every unpublished card in `rows` with its scores as they are
    now. Returns how many were published."""
    now = timezone.now()
    new, changed = [], []
    for row in rows:
        if row["published"]:
            continue
        values = {slot: row[slot] for slot in SLOTS}
        values.update(level=row["pupil"].level, total=row["total"], grade=row["grade"],
                      days_practised=row["days"], published_at=now, published_by=admin)
        card = row["card"]
        if card is None:
            new.append(ReportCard(student=row["pupil"], term=dated.term, **values))
        else:
            for name, value in values.items():
                setattr(card, name, value)
            changed.append(card)
    ReportCard.objects.bulk_create(new)
    ReportCard.objects.bulk_update(changed, [*SLOTS, "level", "total", "grade", "days_practised",
                                             "published_at", "published_by"])
    return len(new) + len(changed)
