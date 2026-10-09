"""
The school-year pages.

    reports       a term's report cards for a teacher's class (comments) or
                  a whole school (the admin publishes them)
    card          one student's card, ready to print: for their teacher and
                  school admin, and once published for their grown-ups
                  behind the For grown-ups PIN
    promote       end of the year: students suggested for promotion from
                  their session average, moved up with the school's usual
                  level tools (apps/schools/levels.py, with undo)
    term_dates    a school's own term dates, when it doesn't keep the
                  platform's

And for a student following the scheme (timetable.py):

    home          their dashboard: this week, today first (accounts.views
                  .dashboard hands over to it)
    weeks         My weeks: every week they've reached, to go back to
    week          one of those weeks
    go            open an entry from the scheme, noting that it was opened
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

from .calendar import break_after_week, dates_from_weeks, last_term, terms_for, week_starts, weeks_in
from .models import TERM_CHOICES as TERM_LABELS
from . import path as own
from . import timetable as tt
from .models import Grading, ReportCard, SchemeEntry, SchemeOpened, SchoolTermDates
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
    """Suggest promotion from the session's published report cards."""
    admin = request.user
    dated = last_term(admin)
    session = dated.term.session if dated else None
    grading = Grading.load()
    students = list(_school_students(admin.school).order_by("level", "first_name", "last_name"))
    averages = {}
    if session:
        averages = {
            row["student"]: row for row in
            ReportCard.objects.filter(student__in=students, term__session=session).exclude(published_at=None)
            .values("student").annotate(average=Avg("total"), terms=Count("pk"))
        }

    if request.method == "POST":
        chosen = set(request.POST.getlist("students"))
        picked = [s for s in students if str(s.pk) in chosen]
        outcome = level_moves.promote(admin, picked)
        moved = len(outcome.changed)
        notes = []
        if outcome.at_top:
            notes.append(f"{len(outcome.at_top)} already in {level_moves.TOP} stayed there")
        if outcome.no_level:
            notes.append(f"{len(outcome.no_level)} with no level yet were left as they are")
        messages.success(request, f"{moved} student{'' if moved == 1 else 's'} promoted."
                                  + (" " + "; ".join(notes).capitalize() + "." if notes else "")
                                  + (" You can undo this under Level changes." if moved else ""))
        return redirect(f"{reverse('schools:dashboard')}#level-changes")

    rows = []
    for student in students:
        found = averages.get(student.pk)
        average = round(found["average"]) if found and found["average"] is not None else None
        rows.append({
            "student": student, "average": average, "terms": found["terms"] if found else 0,
            "suggested": average is not None and average >= grading.pass_mark,
            "next_level": level_moves.next_level(student.level),
        })
    return render(request, "scheme/promote.html", {
        "rows": rows, "session": session, "grading": grading,
        "suggested": sum(1 for r in rows if r["suggested"]),
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


@role_required(User.Role.SCHOOL_ADMIN)
def school_scheme(request):
    """The scheme of work for the school's levels, read-only, with the
    school's own week dates. The scheme itself is set by Diction Masters
    (control room); a school sets its term dates."""
    from .models import DAY_CHOICES, DAY_ORDER, SchemeEntry
    from .timetable import content_url

    school = request.user.school
    levels = sorted(set(_school_students(school).exclude(level="").values_list("level", flat=True)),
                    key=lambda v: level_moves.LEVELS.index(v) if v in level_moves.LEVELS else 99) or level_moves.LEVELS[1:2]
    level = request.GET.get("level") if request.GET.get("level") in level_moves.LEVELS else levels[0]
    raw = request.GET.get("term", "")
    number = int(raw) if raw in {"1", "2", "3"} else (last_term(request.user).number if last_term(request.user) else 1)
    terms = terms_for(school)
    newest = terms[-1].term.session_id if terms else None
    dated = next((t for t in terms if t.term.session_id == newest and t.number == number), None)
    firsts = dict(week_starts(dated)) if dated else {}
    labels = dict(DAY_CHOICES)
    by_week = {}
    for entry in (SchemeEntry.objects.filter(level=level, term=number, is_draft=False)
                  .select_related("group__level", "category", "activity__group__level",
                                  "module_day__week__term__module", "dialogue__level", "sound",
                                  "chapter__term__book", "recital__section", "library_item", "assessment")
                  .order_by("week", "order")):
        by_week.setdefault(entry.week, []).append(
            {"day": labels.get(entry.day) or "Any day", "title": entry.title, "kind": entry.get_kind_display(),
             "url": content_url(entry)})
    # Monday to Friday, "any day" first — not the days' names in A–Z order.
    rank = {label: DAY_ORDER.index(key) for key, label in DAY_CHOICES}
    rank["Any day"] = 0
    for rows in by_week.values():
        rows.sort(key=lambda row: rank.get(row["day"], 0))
    weeks = [{"number": n, "first": firsts.get(n), "rows": by_week.get(n, [])}
             for n in range(1, (weeks_in(dated) if dated else max(by_week or [12])) + 1)]
    return render(request, "scheme/school_scheme.html", {
        "levels": levels, "level": level, "terms": TERM_LABELS, "number": number, "dated": dated,
        "weeks": weeks, "total": sum(len(w["rows"]) for w in weeks),
    })


# ---------------------------------------------------------------------------
# The student's side
# ---------------------------------------------------------------------------

def home(request):
    """A scheme student's dashboard. Called from accounts.views.dashboard."""
    from apps.accounts import switcher
    from apps.accounts.dashboard_data import _greeting

    return render(request, "scheme/home.html", {
        **tt.timetable(request.user),
        "greeting": _greeting(timezone.now()),
        "today": _today(),
        "switcher": switcher.context(request),
    })


def _scheme_student(view):
    """Only a student following the scheme, or an individual learner who
    has chosen one (path.py); anyone else goes home."""
    @login_required(login_url="accounts:login")
    def guard(request, *args, **kwargs):
        user = request.user
        if not (tt.on_scheme(user) or (own.follows_path(user) and own.choice_for(user))):
            return redirect("accounts:dashboard")
        return view(request, *args, **kwargs)

    guard.__name__ = view.__name__
    guard.__doc__ = view.__doc__
    return guard


@_scheme_student
def practise(request):
    """The practice tools a scheme student can always open."""
    return render(request, "scheme/practise.html")


@_scheme_student
def weeks(request):
    """My weeks: the weeks they've reached, newest first."""
    if not tt.on_scheme(request.user):
        return redirect("scheme:lessons")          # individuals: the whole scheme, term by term
    return render(request, "scheme/weeks.html", {"weeks": tt.past_weeks(request.user)})


@_scheme_student
def lessons(request):
    """An individual learner's Lessons: their scheme term by term, week by
    week, day by day — all open, to move around until it's all done."""
    if tt.on_scheme(request.user):
        return redirect("scheme:weeks")
    choice = own.choice_for(request.user)
    found = own.lessons(request.user, choice.level)
    raw = request.GET.get("term", "")
    numbers = [t["number"] for t in found["terms"]]
    if raw.isdigit() and int(raw) in numbers:
        shown = int(raw)
    else:
        shown = found["current"]["term"] if found["current"] else (numbers[0] if numbers else None)
    return render(request, "scheme/lessons.html", {
        **found, "choice": choice, "shown": shown,
        "term": next((t for t in found["terms"] if t["number"] == shown), None),
    })


@_scheme_student
def week(request, term, number):
    if tt.on_scheme(request.user):
        rows = tt.week_rows(request.user, term, number)
    else:
        level = own.choice_for(request.user).level
        rows = None
        if (term, number) in own.open_weeks(request.user, level):
            entries = tt._sorted(tt._entries(level=level, term=term, week=number))
            done = tt.done_for([request.user], entries)[request.user.pk]
            rows = [tt._row(e, done) for e in entries]
    if rows is None:
        raise Http404
    return render(request, "scheme/week.html", {
        "rows": rows, "term_label": dict(TERM_LABELS).get(term, ""), "number": number,
        "done": sum(1 for r in rows if r["done"]), "total": len(rows),
    })


@_scheme_student
def go(request, pk):
    """Open an entry from the scheme: noted, then on to its content. Only
    entries for their level in a week they've reached."""
    user = request.user
    if tt.on_scheme(user):
        entry = get_object_or_404(SchemeEntry, pk=pk, level=user.level, is_draft=False)
        if tt.content_key(entry) not in tt.open_keys(user):
            raise Http404
    else:
        level = own.choice_for(user).level
        entry = get_object_or_404(SchemeEntry, pk=pk, level=level, is_draft=False)
        if (entry.term, entry.week) not in own.open_weeks(user, level):
            raise Http404
    SchemeOpened.objects.get_or_create(user=user, entry=entry)
    return redirect(tt.content_url(entry))


def path_home(request):
    """An individual learner's dashboard: their chosen scheme, the next
    lesson and My weeks — or, with none chosen yet, the choice. Called from
    accounts.views.dashboard."""
    from apps.accounts import switcher
    from apps.accounts.dashboard_data import _greeting

    choice = own.choice_for(request.user)
    if choice is None:
        return choose(request)
    return render(request, "scheme/path_home.html", {
        **own.path(request.user, choice.level),
        "choice": choice,
        "greeting": _greeting(timezone.now()),
        "today": _today(),
        "switcher": switcher.context(request),
    })


@login_required(login_url="accounts:login")
def choose(request):
    """Choose (or change) the scheme to follow. Individual learners only."""
    from .models import SchemeChoice

    if not own.follows_path(request.user):
        return redirect("accounts:dashboard")
    offer = own.schemes_on_offer()
    if request.method == "POST":
        level = request.POST.get("level", "")
        if level in {o["level"] for o in offer}:
            SchemeChoice.objects.update_or_create(user=request.user, defaults={"level": level})
            messages.success(request, f"You're following the {level} scheme. Your first lesson is ready.")
            return redirect("accounts:dashboard")
        messages.error(request, "Choose one of the schemes below.")
    choice = own.choice_for(request.user)
    return render(request, "scheme/choose.html", {
        "offer": offer, "choice": choice, "suggested": own.suggested_level(request.user),
    })


@role_required(User.Role.TEACHER)
def teaching_plan(request):
    """A teacher's plan for the term: every week of the scheme for their
    level, laid out Monday to Friday with the dates, what to prepare for
    the next school day, and how the class is getting on. Printable."""
    teacher = request.user
    levels = teacher.all_levels or level_moves.LEVELS[1:2]
    level = request.GET.get("level") if request.GET.get("level") in levels else levels[0]
    current = last_term(teacher)
    raw = request.GET.get("term", "")
    number = int(raw) if raw in {"1", "2", "3"} else (current.number if current else 1)
    pupils = list(pupils_of(teacher).filter(level=level))
    return render(request, "scheme/teaching_plan.html", {
        **tt.term_plan(teacher, level, number, pupils),
        "levels": levels, "level": level, "number": number, "terms": TERM_LABELS, "today": _today(),
    })
