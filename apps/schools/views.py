from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import switcher
from apps.accounts.decorators import role_required
from apps.accounts.models import User

from . import levels as level_moves


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
        "level_choices": level_moves.LEVELS,
        "level_history": level_moves.batches(school),
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


# ---------------------------------------------------------------------------
# Levels: change one person's, move or promote several, undo
# ---------------------------------------------------------------------------

def _name(member):
    return member.get_full_name() or member.login_name


def _people(n, what="student"):
    return f"{n} {what}{'' if n == 1 else 's'}"


def _report(request, outcome, verb):
    """One clear message for what a level change did, and didn't, do."""
    changed = outcome.changed
    if len(changed) == 1:
        member, before, after = changed[0]
        text = f"{_name(member)} {verb} from {before} to {after}."
    elif changed:
        text = f"{len(changed)} {'students' if all(m.role == User.Role.STUDENT for m, _b, _a in changed) else 'people'} {verb}."
    else:
        text = ""
    notes = []
    if outcome.at_top:
        notes.append(f"{_people(len(outcome.at_top))} already in {level_moves.TOP} stayed there")
    if outcome.no_level:
        n = len(outcome.no_level)
        notes.append(f"{_people(n)} with no level yet {'was' if n == 1 else 'were'} left as {'they are' if n > 1 else 'before'}"
                     " (use Change to give them a level)")
    if outcome.unchanged and not changed:
        notes.append("nobody needed changing — they're already there")
    if notes:
        note = "; ".join(notes)
        text = (text + " " if text else "") + note[0].upper() + note[1:] + "."
    if changed:
        text += " You can undo this under Level changes."
        messages.success(request, text)
    else:
        messages.info(request, text or "Nothing was changed.")


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def member_level(request, pk):
    """One teacher's or student's levels, from the Change level dialog."""
    member = _member(request, pk)
    try:
        outcome = level_moves.set_levels(request.user, member, request.POST.getlist("levels"))
    except ValueError as error:
        messages.error(request, str(error))
    else:
        _report(request, outcome, "moved")
    return redirect(f"{reverse('schools:dashboard')}#{member.role}s")


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def bulk_levels(request):
    """Move or promote the people ticked in the Teachers or Students list."""
    role = request.POST.get("role")
    if role not in (User.Role.TEACHER, User.Role.STUDENT):
        role = User.Role.STUDENT
    ids = [int(pk) for pk in request.POST.getlist("members") if pk.isdigit()]
    members = list(User.objects.filter(pk__in=ids, school=request.user.school, role=role, is_active=True,
                                       is_staff=False, is_superuser=False).order_by("first_name", "last_name"))
    back = f"{reverse('schools:dashboard')}#{role}s"
    if not members:
        messages.error(request, f"Tick at least one {role} first.")
        return redirect(back)
    action = request.POST.get("action")
    if action == "promote" and role == User.Role.STUDENT:
        _report(request, level_moves.promote(request.user, members), "promoted to their next level")
    elif action == "move":
        try:
            outcome = level_moves.move(request.user, members, request.POST.get("level", ""))
        except ValueError as error:
            messages.error(request, str(error))
        else:
            _report(request, outcome, f"moved to {request.POST.get('level')}")
    else:
        messages.error(request, "Choose what to do with them.")
    return redirect(back)


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def undo_levels(request, batch):
    restored, skipped = level_moves.undo(request.user, batch)
    if restored:
        text = f"Undone: {_people(len(restored), 'person') if len(restored) == 1 else str(len(restored)) + ' people'} back in their earlier level."
        if skipped:
            text += f" {len(skipped)} had been moved again since, so they were left as they are."
        messages.success(request, text)
    elif skipped:
        messages.info(request, "Nothing was undone: everyone in that change has been moved again since.")
    else:
        messages.info(request, "That change was already undone.")
    return redirect(f"{reverse('schools:dashboard')}#level-changes")
