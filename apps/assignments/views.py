"""
Assignments for teachers (their classes) and school admins (the school's):

    assignments   every assignment, due soonest first, with how many have done it
    new           set one: classes, work, due date, a note; the pupils are told
    detail        one assignment: each pupil done or not (or overdue), change
                  the due date or note, or delete it

Pupils see theirs on their home and in the bell (apps/notifications).
"""

from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.notify import notify_many
from apps.schools import classes as school_classes

from . import progress
from .forms import AssignmentForm, ChangeForm
from .models import Assignment

SHOWN = 60


def _classes_for(user):
    """The classes this person may set work for."""
    from apps.schools.models import SchoolClass

    if user.is_school_admin:
        ids = [c.pk for c in school_classes.this_year(user.school)]
    else:
        ids = [c.pk for c in school_classes.this_year_of(user)]
    return SchoolClass.objects.filter(pk__in=ids).order_by("grade", "name")


def _visible(user):
    found = Assignment.objects.filter(school=user.school)
    if user.is_school_admin:
        return found
    return found.filter(Q(created_by=user) | Q(classes__teachers=user)).distinct()


def _get(user, pk):
    found = _visible(user).filter(pk=pk).first()
    if found is None:
        raise Http404("No such assignment.")
    return found


def _tell_pupils(assignment):
    due = f"Due {assignment.due_on:%A} {assignment.due_on.day} {assignment.due_on:%B}."
    note = f" {assignment.note}" if assignment.note else ""
    notify_many(progress.pupils(assignment).values_list("pk", flat=True), Notification.Kind.ASSIGNMENT,
                f"New assignment: {assignment.title}", (due + note)[:300], assignment.url,
                key=f"assignment-{assignment.pk}")


@role_required(User.Role.TEACHER, User.Role.SCHOOL_ADMIN)
def assignments(request):
    today = timezone.localdate()
    found = list(_visible(request.user).prefetch_related("classes").select_related(
        "group__level", "module_day__week__term__module", "lesson", "assessment").order_by("-due_on")[:SHOWN])
    rows = [{"assignment": a, "summary": progress.summary(a, today), "past": a.due_on < today} for a in found]
    current = sorted((r for r in rows if not r["past"]), key=lambda r: r["assignment"].due_on)
    return render(request, "assignments/list.html", {
        "current": current, "past": [r for r in rows if r["past"]], "today": today,
        "can_set": _classes_for(request.user).exists(),
    })


@role_required(User.Role.TEACHER, User.Role.SCHOOL_ADMIN)
def new(request):
    classes = _classes_for(request.user)
    if not classes.exists():
        messages.info(request, "You need a class first. Your school admin gives you your classes on the Classes page.")
        return redirect("assignments:list")
    form = AssignmentForm(request.POST or None, classes=classes,
                          initial={"due_on": timezone.localdate() + timedelta(days=7)})
    if request.method == "POST" and form.is_valid():
        made = form.save(request.user.school, request.user)
        _tell_pupils(made)
        messages.success(request, f"Set: {made.title}, due {made.due_on:%A} {made.due_on.day} {made.due_on:%B}. "
                                  "Your pupils have been told.")
        return redirect("assignments:detail", pk=made.pk)
    return render(request, "assignments/new.html", {"form": form})


@role_required(User.Role.TEACHER, User.Role.SCHOOL_ADMIN)
def detail(request, pk):
    assignment = _get(request.user, pk)
    form = ChangeForm(instance=assignment)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            title = assignment.title
            assignment.delete()
            messages.success(request, f"Deleted: {title}.")
            return redirect("assignments:list")
        form = ChangeForm(request.POST, instance=assignment)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect("assignments:detail", pk=assignment.pk)
    found = progress.summary(assignment)
    by_class = {}
    for row in found["rows"]:
        by_class.setdefault(row["pupil"].school_class, []).append(row)
    return render(request, "assignments/detail.html", {
        "assignment": assignment, "summary": found, "form": form, "today": timezone.localdate(),
        "by_class": sorted(by_class.items(), key=lambda pair: (school_classes.GRADE_ORDER.get(pair[0].grade, 99), pair[0].name)),
    })
