"""
Reminders: what someone still has to do, worked out live (never saved), so
they're always true and go away once done. For the bell, next to the saved
updates (models.Notification).

    learners (pupils and individual learners)
        an assignment due within 2 days, or late
        a test started but not handed in
        a school test closing within 3 days that they haven't sat
        a lesson started but not finished (Today's lesson)
        a streak that ends tonight unless they practise
    teachers
        their assignments due (or just past) that some pupils haven't done
        answers waiting to be marked
        pupils who need help (My class)
    school admins
        password help requests still open
        students with no class
        the school's trial ending within 7 days

for_user(user) gives [{"kind", "icon", "title", "body", "url"}], cached for a
minute per person; forget(user_id) drops that (a new update arrived).
"""

from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

CACHE_SECONDS = 60
TEST_SOON_DAYS = 3
TRIAL_SOON_DAYS = 7


def _key(user_id):
    return f"notif-reminders-{user_id}"


def forget(user_id):
    cache.delete(_key(user_id))


def for_user(user):
    if not getattr(user, "is_authenticated", False):
        return []
    found = cache.get(_key(user.pk))
    if found is None:
        found = _work_out(user)
        cache.set(_key(user.pk), found, CACHE_SECONDS)
    return found


def _work_out(user):
    if user.role in ("student", "individual"):
        return _learner(user)
    if user.role == "teacher":
        return _teacher(user)
    if user.role == "school_admin":
        return _admin(user)
    return []


def _item(kind, icon, title, body, url):
    return {"kind": kind, "icon": icon, "title": title, "body": body, "url": url}


def _learner(user):
    from apps.accounts.dashboard_data import _events, _local_date, _streak, todays_lesson
    from apps.assessments.models import Assessment, Attempt

    out = []
    now = timezone.now()
    started = list(Attempt.objects.filter(user=user, status=Attempt.Status.IN_PROGRESS)
                   .select_related("assessment").order_by("-started_at")[:3])
    for attempt in started:
        out.append(_item("test", "task", f"Finish your test: {attempt.assessment.title}",
                         "You started it but haven't handed it in.",
                         reverse("assessments:take", args=[attempt.pk])))
    if user.school_id and user.level:
        sat = Attempt.objects.filter(user=user).values("assessment_id")
        closing = (Assessment.objects.filter(is_published=True, kind__in=["ca", "exam"], level=user.level,
                                             closes_at__gt=now, closes_at__lte=now + timedelta(days=TEST_SOON_DAYS))
                   .exclude(pk__in=sat).exclude(opens_at__gt=now).order_by("closes_at")[:3])
        for test in closing:
            out.append(_item("test", "clock", f"{test.title} closes soon",
                             f"Sit it before {timezone.localtime(test.closes_at):%A %H:%M}.",
                             reverse("assessments:detail", args=[test.slug])))
    from apps.assignments.progress import open_for

    for item in open_for(user, _local_date(now)):
        if item["state"] == "later":
            continue
        assignment = item["assignment"]
        when = {"overdue": "Late", "today": "Due today"}.get(item["state"], "Due tomorrow" if item["days"] == 1 else "Due soon")
        out.append(_item("assignment", "task", f"{when}: {assignment.title}",
                         assignment.note or "An assignment from your teacher.", assignment.url))
    lesson = todays_lesson(user)
    if lesson and lesson.get("label") == "Carry on where you stopped":      # a lesson started, not finished
        out.append(_item("lesson", "play", f"You haven't finished {lesson['title']}",
                         f"Carry on where you stopped: {lesson['detail']}.", lesson["url"]))
    today = _local_date(now)
    active = {_local_date(event[0]) for event in _events(user)}
    streak = _streak(active, today)
    if streak and today not in active:
        out.append(_item("streak", "flame", f"Keep your {streak}-day streak going!",
                         "Practise today, or it starts again tomorrow.", reverse("accounts:dashboard")))
    return out


def _teacher(user):
    from apps.accounts.access import pupils_of
    from apps.assessments.views import markable
    from apps.schools.class_progress import class_progress

    out = []
    to_mark = markable(user).count()
    if to_mark:
        out.append(_item("to_mark", "task", f"{to_mark} answer{'s' if to_mark != 1 else ''} to mark",
                         "Your pupils are waiting for your marks.", reverse("assessments:marking_queue")))
    from apps.assignments.models import Assignment
    from apps.assignments.progress import summary

    today = timezone.localdate()
    due = (Assignment.objects.filter(created_by=user, due_on__lte=today + timedelta(days=1),
                                     due_on__gte=today - timedelta(days=7)).order_by("due_on")[:5])
    for assignment in due:
        left = summary(assignment, today)["left"]
        if left:
            when = "was due" if assignment.due_on < today else "is due"
            out.append(_item("assignment", "task", f"{left} pupil{'s' if left != 1 else ''} haven't done {assignment.title}",
                             f"It {when} {assignment.due_on:%A}.", reverse("assignments:detail", args=[assignment.pk])))
    pupils = pupils_of(user)
    if pupils.exists():
        need = class_progress(pupils)["summary"].get("needs_help", 0)
        if need:
            out.append(_item("help", "hand", f"{need} pupil{'s' if need != 1 else ''} may need help",
                             "Stuck on an activity, or quiet for a while.", reverse("schools:class_dashboard")))
    return out


def _admin(user):
    from apps.accounts.models import PasswordHelpRequest, User

    out = []
    school = user.school
    if school is None:
        return out
    help_open = PasswordHelpRequest.objects.filter(school=school, resolved_at__isnull=True).count()
    if help_open:
        out.append(_item("help", "lock", f"{help_open} password help request{'s' if help_open != 1 else ''}",
                         "Set them a new password from the dashboard.", reverse("schools:dashboard") + "#logins"))
    unplaced = User.objects.filter(school=school, role=User.Role.STUDENT, is_active=True, school_class__isnull=True).count()
    if unplaced:
        out.append(_item("class", "school", f"{unplaced} student{'s' if unplaced != 1 else ''} with no class",
                         "Put them in a class on the Classes page.", reverse("schools:classes")))
    try:
        from apps.billing.access import status_for

        status = status_for(user) or {}
    except Exception:                      # billing is read here only; never break the bell over it
        status = {}
    days = status.get("days_left")
    if status.get("state") == "trial" and days is not None and days <= TRIAL_SOON_DAYS:
        out.append(_item("plan", "card", f"Your free trial ends in {days} day{'s' if days != 1 else ''}",
                         "Choose a plan so everyone keeps learning.", reverse("billing:account")))
    return out
