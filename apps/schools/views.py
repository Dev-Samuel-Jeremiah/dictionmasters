from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import switcher
from apps.accounts.decorators import role_required
from apps.accounts.models import User


@role_required(User.Role.SCHOOL_ADMIN)
def dashboard(request):
    """The school admin's page. Teachers and students both sign up with the
    school code; the school's plan sets how many teachers can join."""
    school = request.user.school
    codes = school.access_codes.select_related("used_by").all()
    context = {
        "school": school,
        "plan": school.chosen_plan(),
        "teacher_link": request.build_absolute_uri(reverse("accounts:join_with_code")) + f"?school={school.code}",
        "teachers": school.teachers,
        "students": school.students,
        "removed": school.removed_members,
        "switcher": switcher.context(request),
        "pending_codes": codes.filter(used_by__isnull=True, role="teacher"),
    }
    return render(request, "schools/dashboard.html", context)


def _member(request, pk):
    """A teacher or student of this admin's own school, never anyone else."""
    return get_object_or_404(
        User, pk=pk, school=request.user.school,
        role__in=(User.Role.TEACHER, User.Role.STUDENT), is_staff=False, is_superuser=False,
    )


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def remove_member(request, pk):
    """Take a teacher or student off the school. Their account is switched
    off, so they're signed out and can't sign in, and their place on the
    plan is free again. Nothing they did is deleted: the admin can restore
    them from the dashboard."""
    member = _member(request, pk)
    if member.is_active:
        member.is_active = False
        member.save(update_fields=["is_active"])
        member.device_logins.all().delete()          # off every family device's account switcher too
    messages.success(request, f"{member.get_full_name() or member.login_name} was removed. "
                              "They can no longer sign in, and their place is free. You can restore them below.")
    return redirect(f"{reverse('schools:dashboard')}#{member.role}s")


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def restore_member(request, pk):
    """Bring a removed teacher or student back, if the plan has room."""
    member = _member(request, pk)
    school = request.user.school
    if not member.is_active:
        full = school.teachers_full if member.role == User.Role.TEACHER else school.students_full
        if full:
            what = "teacher" if member.role == User.Role.TEACHER else "student"
            messages.error(request, f"There's no free {what} place on your plan, so "
                                    f"{member.get_full_name() or member.login_name} can't be restored. "
                                    f"Remove someone else or upgrade your plan first.")
            return redirect(f"{reverse('schools:dashboard')}#removed")
        member.is_active = True
        member.save(update_fields=["is_active"])
    messages.success(request, f"{member.get_full_name() or member.login_name} is back and can sign in again.")
    return redirect(f"{reverse('schools:dashboard')}#{member.role}s")
