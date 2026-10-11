"""
The school-year pages.

    reports       a term's report cards for a teacher's class (comments) or
                  a whole school (the admin publishes them)
    card          one student's card, ready to print: for their teacher and
                  school admin, and once published for their grown-ups
                  behind the For grown-ups PIN
    promote       end of the year: students suggested for promotion from
                  their session average, moved up a grade by class
                  (apps/schools/classes.promote, with undo)
    term_dates    a school's own term dates, when it doesn't keep the
                  platform's

The scheme of work (week-by-week lessons) is retired: students open every
tool their grade allows from Learn (apps/accounts/access.can_use_tool).
Its tables are kept, unused, so nothing published or done is lost.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts import grown_ups
from apps.accounts.access import is_pupil_of, pupils_of
from apps.accounts.decorators import role_required
from apps.accounts.models import User
from apps.schools import levels as level_moves

from .calendar import break_after_week, dates_from_weeks, last_term, terms_for, weeks_in
from .models import Grading, ReportCard, SchoolTermDates
from .results import publish, save_comments, term_results


def _school_students(school):
    return User.objects.filter(school=school, role=User.Role.STUDENT, is_active=True)


def _chosen_term(request, terms):
    """The term asked for (?term=), or the current / latest one."""
    raw = request.GET.get("term") or request.POST.get("term") or ""
    if raw.isdigit():
        found = next((t for t in terms if t.term.pk == int(raw)), None)
        if found:
            return found
    return last_term(request.user)


@role_required(User.Role.TEACHER, User.Role.SCHOOL_ADMIN)
def reports(request):
    user = request.user
    is_admin = user.is_school_admin
    terms = [t for t in terms_for(user.school) if t.starts <= _today()]
    dated = _chosen_term(request, terms)
    pupils = _school_students(user.school) if is_admin else pupils_of(user)
    level = request.GET.get("level") or request.POST.get("level") or ""
    levels = sorted(set(pupils.exclude(level="").values_list("level", flat=True)),
                    key=lambda v: level_moves.LEVELS.index(v) if v in level_moves.LEVELS else 99)
    if level in levels:
        pupils = pupils.filter(level=level)
    else:
        level = ""

    rows = term_results(pupils, dated) if dated else []
    back = f"{reverse('scheme:reports')}?term={dated.term.pk if dated else ''}&level={level}"
    if request.method == "POST" and dated:
        if request.POST.get("action") == "publish":
            if not is_admin:
                raise PermissionDenied("Only the school admin publishes report cards.")
            count = publish(user, rows, dated)
            messages.success(request, f"{count} report card{'' if count == 1 else 's'} published for {dated}. "
                                      "Families can now see them on For grown-ups.")
        else:
            comments = {row["pupil"].pk: request.POST.get(f"comment-{row['pupil'].pk}") for row in rows}
            count = save_comments(user, rows, dated, comments)
            messages.success(request, "Comments saved." if count else "Nothing to save.")
        return redirect(back)

    return render(request, "scheme/reports.html", {
        "terms": terms, "dated": dated, "rows": rows, "is_admin": is_admin,
        "levels": levels, "level": level, "grading": Grading.load(),
        "unpublished": sum(1 for r in rows if not r["published"]),
    })


def _today():
    return timezone.localdate()


@login_required(login_url="accounts:login")
def card(request, term_pk, student_pk):
    user = request.user
    student = get_object_or_404(User, pk=student_pk, role=User.Role.STUDENT)
    dated = next((t for t in terms_for(student.school) if t.term.pk == term_pk), None)
    if dated is None:
        raise Http404
    row = term_results([student], dated)[0]

    staff_side = (
        user.is_staff
        or (user.is_school_admin and user.school_id and user.school_id == student.school_id)
        or is_pupil_of(user, student)
    )
    if not staff_side:
        # The student's own account: their grown-ups, once it's published,
        # behind the For grown-ups PIN.
        if user.pk != student.pk or not row["published"]:
            raise Http404
        if grown_ups.needs_pin(user) and not grown_ups.is_unlocked(request):
            return redirect("accounts:grown_ups")
    return render(request, "scheme/card.html", {
        "student": student, "dated": dated, "row": row, "grading": Grading.load(), "staff_side": staff_side,
    })


@role_required(User.Role.SCHOOL_ADMIN)
def promote(request):
    """The end of the year: move the school's classes up a grade
    (apps/schools/classes.promote). Students whose session average reaches
    the promotion mark are ticked; the rest stay in their grade. Into the
    next school year when the calendar has it."""
    from apps.schools import classes as school_classes, grades

    admin = request.user
    school = admin.school
    dated = last_term(admin)
    session = dated.term.session if dated else None
    grading = Grading.load()
    taught = school_classes.this_year(school)
    order = {c.pk: i for i, c in enumerate(taught)}
    students = sorted(_school_students(school).filter(school_class__in=taught).select_related("school_class"),
                      key=lambda s: (order[s.school_class_id], s.first_name.lower(), s.last_name.lower()))
    averages = {}
    if session:
        averages = {
            row["student"]: row for row in
            ReportCard.objects.filter(student__in=students, term__session=session).exclude(published_at=None)
            .values("student").annotate(average=Avg("total"), terms=Count("pk"))
        }
    later = school_classes.next_year(school)

    if request.method == "POST":
        chosen = set(request.POST.getlist("students"))
        outcome = school_classes.promote(admin, school, [s for s in students if str(s.pk) in chosen])
        said = [f"{len(outcome.promoted)} student{'' if len(outcome.promoted) == 1 else 's'} moved up a grade"]
        if outcome.graduated:
            said.append(f"{len(outcome.graduated)} graduated")
        if outcome.stayed:
            said.append(f"{len(outcome.stayed)} stayed in their grade")
        messages.success(request, "; ".join(said).capitalize() + "."
                                  + (f" Your classes are now in {outcome.year}." if outcome.year else "")
                                  + " You can undo this under Level changes.")
        return redirect(f"{reverse('schools:dashboard')}#level-changes")

    groups = []
    for found in taught:
        rows = []
        for student in (s for s in students if s.school_class_id == found.pk):
            got = averages.get(student.pk)
            average = round(got["average"]) if got and got["average"] is not None else None
            up = grades.next_grade(found.grade)
            rows.append({
                "student": student, "average": average, "terms": got["terms"] if got else 0,
                "suggested": average is not None and average >= grading.pass_mark,
                "goes_to": f"{grades.label_for(up)} {found.name}".strip() if up else "Graduates",
            })
        if rows:
            groups.append({"class": found, "rows": rows})
    return render(request, "scheme/promote.html", {
        "groups": groups, "session": session, "grading": grading, "next_year": later,
        "suggested": sum(1 for g in groups for r in g["rows"] if r["suggested"]),
        "unplaced": _school_students(school).filter(school_class__isnull=True).count(),
    })


@role_required(User.Role.SCHOOL_ADMIN)
def term_dates(request):
    """A school's own dates for the terms still to finish."""
    school = request.user.school
    terms = [t for t in terms_for(school) if t.ends >= _today()]
    own = {d.term_id: d for d in SchoolTermDates.objects.filter(school=school)}
    errors = {}
    if request.method == "POST":
        from datetime import date

        for dated in terms:
            key = dated.term.pk
            if request.POST.get(f"platform-{key}"):
                SchoolTermDates.objects.filter(school=school, term=dated.term).delete()
                continue
            try:
                values = {name: (date.fromisoformat(request.POST[f"{name}-{key}"])
                                 if request.POST.get(f"{name}-{key}") else None)
                          for name in ("starts", "ends", "break_starts", "break_ends")}
                weeks = int(request.POST.get(f"weeks-{key}") or 0)
                after = int(request.POST.get(f"break_after-{key}") or 0)
            except ValueError:
                errors[key] = "One of the dates isn't a date."
                continue
            # Teaching weeks given: the end and break follow from the first day.
            if weeks and values["starts"] and request.POST.get(f"by_weeks-{key}"):
                values["ends"], values["break_starts"], values["break_ends"] = dates_from_weeks(
                    values["starts"], weeks, after)
            if not values["starts"] or not values["ends"]:
                continue
            same = all(values[n] == getattr(dated.term, n) for n in values)
            if same:
                SchoolTermDates.objects.filter(school=school, term=dated.term).delete()
                continue
            record = own.get(key) or SchoolTermDates(school=school, term=dated.term)
            for name, value in values.items():
                setattr(record, name, value)
            try:
                record.full_clean()
            except ValidationError as problem:
                errors[key] = " ".join(problem.messages)
                continue
            record.save()
        if not errors:
            messages.success(request, "Term dates saved.")
            return redirect("scheme:term_dates")
        terms = [t for t in terms_for(school) if t.ends >= _today()]
    return render(request, "scheme/term_dates.html", {
        "terms": [{"dated": t, "own": t.term.pk in own, "error": errors.get(t.term.pk, ""),
                   "weeks": weeks_in(t), "break_after": break_after_week(t)} for t in terms],
    })
