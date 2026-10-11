"""
Who has done an assignment, from what the site already records: nobody
ticks anything off.

    EchoSpell group        the group completed (echospell.GroupProgress)
    Learning Modules day   the day completed (learning_modules.DayProgress)
    44 Academy / Tricks    every part with something in it opened, and every
                           assessment activity passed (a recording counts once
                           sent), the same rule as apps/tricks/progress.journey
    test                   handed in (submitted, waiting for marking or marked)

done_ids(assignment, pupil_ids) answers for many pupils in a few queries;
nothing is asked once per pupil.

    pupils(assignment)         the active students in its classes
    summary(assignment)        {"pupils", "done", "left", "overdue", "rows"}
    open_for(student, today)   their assignments not done yet, soonest first
"""

from django.utils import timezone

from .models import Assignment

K = Assignment.Kind


def done_ids(assignment, pupil_ids):
    pupil_ids = list(pupil_ids)
    if not pupil_ids:
        return set()
    if assignment.kind == K.GROUP:
        from apps.echospell.models import GroupProgress

        return set(GroupProgress.objects.filter(group_id=assignment.group_id, user_id__in=pupil_ids)
                   .values_list("user_id", flat=True))
    if assignment.kind == K.MODULE_DAY:
        from apps.learning_modules.models import DayProgress

        return set(DayProgress.objects.filter(day_id=assignment.module_day_id, user_id__in=pupil_ids)
                   .values_list("user_id", flat=True))
    if assignment.kind == K.TEST:
        from apps.assessments.models import Attempt

        handed_in = [Attempt.Status.SUBMITTED, Attempt.Status.AWAITING, Attempt.Status.MARKED]
        return set(Attempt.objects.filter(assessment_id=assignment.assessment_id, user_id__in=pupil_ids,
                                          status__in=handed_in).values_list("user_id", flat=True))
    if assignment.kind in (K.SOUND, K.TRICK):
        return _lesson_done(assignment.lesson, pupil_ids)
    return set()


def _lesson_done(lesson, pupil_ids):
    from apps.tricks.models import LessonActivityAttempt, LessonProgress
    from apps.tricks.progress import _activities_by_lesson, _tabs_with_content

    if lesson is None:
        return set()
    needed = set(_tabs_with_content([lesson]).get(lesson.pk, []))
    seen = dict(LessonProgress.objects.filter(lesson=lesson, user_id__in=pupil_ids).values_list("user_id", "tabs_seen"))
    activities = _activities_by_lesson([lesson]).get(lesson.pk, [])
    passed = {}
    for user_id, activity_id, status, ok in (
            LessonActivityAttempt.objects.filter(activity__in=activities, user_id__in=pupil_ids)
            .values_list("user_id", "activity_id", "status", "passed")):
        # Passed, or a recording sent (only recordings wait for a teacher).
        if ok or status == LessonActivityAttempt.STATUS_AWAITING:
            passed.setdefault(user_id, set()).add(activity_id)
    wanted = {a.pk for a in activities}
    return {
        user_id for user_id, tabs in seen.items()
        if needed <= set(tabs or []) and wanted <= passed.get(user_id, set())
    }


def pupils(assignment):
    from apps.accounts.models import User

    return User.objects.filter(role=User.Role.STUDENT, is_active=True, school_class__in=assignment.classes.all())


def summary(assignment, today=None):
    """Its pupils with done or not, for the teacher's page."""
    today = today or timezone.localdate()
    found = list(pupils(assignment).select_related("school_class").order_by("school_class__grade", "first_name", "last_name"))
    done = done_ids(assignment, [p.pk for p in found])
    overdue = assignment.due_on < today
    rows = [{"pupil": p, "done": p.pk in done, "overdue": overdue and p.pk not in done} for p in found]
    count = sum(1 for r in rows if r["done"])
    return {"pupils": len(rows), "done": count, "left": len(rows) - count,
            "overdue": sum(1 for r in rows if r["overdue"]), "rows": rows,
            "percent": round(count * 100 / len(rows)) if rows else 0}


def open_for(student, today=None):
    """The student's assignments not done yet, soonest due first, each with
    its state: "overdue", "today", "soon" (within 2 days) or "later"."""
    if not (getattr(student, "is_authenticated", False) and student.is_student and student.school_class_id):
        return []
    today = today or timezone.localdate()
    found = list(Assignment.objects.filter(classes=student.school_class_id)
                 .select_related("group__level", "module_day__week__term__module", "lesson", "assessment")
                 .order_by("due_on", "pk").distinct()[:20])
    out = []
    for assignment in found:
        if student.pk in done_ids(assignment, [student.pk]):
            continue
        days = (assignment.due_on - today).days
        state = "overdue" if days < 0 else "today" if days == 0 else "soon" if days <= 2 else "later"
        out.append({"assignment": assignment, "state": state, "days": days})
    return out
