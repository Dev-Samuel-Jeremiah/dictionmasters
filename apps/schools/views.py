from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import switcher
from apps.accounts.access import pupils_of
from apps.accounts.dashboard_data import learner_dashboard
from apps.accounts.decorators import role_required
from apps.accounts.models import User

from . import levels as level_moves
from .class_progress import class_progress
from . import logins
from apps.accounts import password_reset


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
        "logins_unlocked": logins.is_unlocked(request),
        "logins_minutes": logins.minutes_left(request),
        "logins_recovery": logins.recovery_ready(),
        "help_requests": list(password_reset.open_requests(school)),
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


# ---------------------------------------------------------------------------
# Logins: show, reset and download (apps/schools/logins.py)
# ---------------------------------------------------------------------------

def _xlsx(content, filename):
    from django.http import HttpResponse

    from apps.manage.bulk_students import XLSX

    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _locked(request):
    """The answer when the login tools haven't been unlocked."""
    from django.http import JsonResponse

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"locked": True, "error": "Confirm your password first, in Login details."}, status=403)
    messages.error(request, "Confirm your password first to see or download login details.")
    return redirect(f"{reverse('schools:dashboard')}#logins")


def _ids(request):
    return [int(pk) for pk in request.POST.getlist("members") if pk.isdigit()]


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def logins_unlock(request):
    if request.POST.get("lock"):
        logins.lock(request)
        messages.success(request, "Login details are locked again.")
    elif logins.unlock(request, request.POST.get("password", "")):
        messages.success(request, f"Login details unlocked for {logins.UNLOCK_MINUTES} minutes.")
    else:
        messages.error(request, "That password isn't right. Use the password you sign in to Diction Masters with.")
    return redirect(f"{reverse('schools:dashboard')}#logins")


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def logins_download(request):
    """An Excel sheet of logins: everyone, teachers or students, a level,
    or the people ticked. Optionally gives a new password to anyone whose
    current one can't be shown, so every row has a password."""
    if not logins.is_unlocked(request):
        return _locked(request)
    role = request.POST.get("role", "")
    level = request.POST.get("level", "")
    picked = _ids(request)
    people = list(logins.members(request.user, role=role, level=level if level in level_moves.LEVELS else "",
                                 ids=picked if request.POST.get("picked") else None))
    if not people:
        messages.error(request, "There's nobody to include in that sheet.")
        return redirect(f"{reverse('schools:dashboard')}#logins")
    new = {}
    if request.POST.get("fill_missing"):
        for person in people:
            if logins.password_of(person) is None:
                new[person.pk] = logins.reset(request.user, person)
    who = {"teacher": "Teachers", "student": "Students"}.get(role, "Everyone")
    title = "Login details · " + who + (f" · {level}" if level else "")
    note = ("Keep this sheet private. " + (f"{len(new)} account(s) without a recoverable password were given a new one, so every row has a password that works. " if new else "")
            + "Passwords can be reset from the school dashboard at any time.")
    content, filename = logins.sheet(request, logins.accounts(people, new), title=title, note=note)
    return _xlsx(content, filename)


@role_required(User.Role.SCHOOL_ADMIN)
def member_login(request, pk):
    """One person's login, for the Login dialog."""
    from django.http import JsonResponse

    if not logins.is_unlocked(request):
        return _locked(request)
    member = _member(request, pk)
    password = logins.password_of(member)
    logins.logger.info("School logins: admin %s viewed the login of %s", request.user.pk, member.pk)
    return JsonResponse({"name": _name(member), "login": member.login_name, "role": member.get_role_display(),
                         "password": password or "", "available": password is not None})


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def member_reset(request, pk):
    """A new password for one person: one chosen by the admin, or a simple one made up."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.http import JsonResponse

    if not logins.is_unlocked(request):
        return _locked(request)
    member = _member(request, pk)
    chosen = request.POST.get("password", "").strip()
    if chosen:
        if len(chosen) < 6:
            return JsonResponse({"error": "Use at least 6 characters, or leave it empty to make one up."}, status=400)
        if member.role == User.Role.TEACHER:
            try:
                validate_password(chosen, member)
            except ValidationError as error:
                return JsonResponse({"error": " ".join(error.messages)}, status=400)
    password = logins.reset(request.user, member, chosen)
    return JsonResponse({"name": _name(member), "login": member.login_name, "password": password})


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def bulk_reset(request):
    """New passwords for everyone ticked, handed back as an Excel sheet."""
    if not logins.is_unlocked(request):
        return _locked(request)
    people = list(logins.members(request.user, ids=_ids(request)))
    if not people:
        messages.error(request, "Tick the people whose passwords to reset.")
        return redirect(reverse("schools:dashboard"))
    new = {person.pk: logins.reset(request.user, person) for person in people}
    content, filename = logins.sheet(
        request, logins.accounts(people, new), title="New passwords",
        note="These passwords were just reset: the old ones no longer work. Keep this sheet private.")
    return _xlsx(content, filename.replace("-logins-", "-new-passwords-"))


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def dismiss_help(request, pk):
    """A password help request that needs nothing (they remembered it)."""
    from apps.accounts.models import PasswordHelpRequest
    from django.utils import timezone

    PasswordHelpRequest.objects.filter(pk=pk, school=request.user.school, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolved_by=request.user)
    messages.success(request, "Request dismissed.")
    return redirect(f"{reverse('schools:dashboard')}#logins")


# ---------------------------------------------------------------------------
# A teacher's class: how each pupil is getting on
# ---------------------------------------------------------------------------

@role_required(User.Role.TEACHER)
def class_dashboard(request):
    """My class: every pupil in the teacher's levels, with what they've done
    lately. A teacher of several levels can look at one at a time."""
    pupils = pupils_of(request.user)
    levels = request.user.all_levels
    level = request.GET.get("level", "")
    if level and level in levels:
        pupils = pupils.filter(level=level)
    else:
        level = ""
    return render(request, "schools/class_dashboard.html", {
        **class_progress(pupils),
        "levels": levels if len(levels) > 1 else [],
        "level": level,
    })


@role_required(User.Role.TEACHER)
def pupil_detail(request, pk):
    """One pupil's progress, read-only. Only the teacher's own pupils."""
    pupil = get_object_or_404(pupils_of(request.user), pk=pk)
    return render(request, "schools/pupil_detail.html", {**learner_dashboard(pupil), "pupil": pupil})
