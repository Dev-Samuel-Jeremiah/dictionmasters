"""
The school calendar in the control room: each school year's three terms,
set the way schools think of them — the first day, how many teaching weeks,
and the week the mid-term break follows — with the end and break dates
worked out (apps/scheme/calendar.dates_from_weeks). Each term is shown as a
strip of its weeks, as students will have them. Exact dates can still be
set on the Terms screen. A school can shift its own dates from its
dashboard (apps/scheme/views.term_dates).
"""

from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.scheme.calendar import break_after_week, dates_from_weeks, week_starts, weeks_in
from apps.scheme.models import TERM_CHOICES, Session, Term

from .views import _base_context, staff_only

MAX_WEEKS = 14


@staff_only
def calendar_editor(request):
    sessions = list(Session.objects.prefetch_related("terms"))
    raw = request.GET.get("year") or request.POST.get("year") or ""
    session = next((s for s in sessions if str(s.pk) == raw), sessions[0] if sessions else None)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_year":
            name = request.POST.get("name", "").strip()[:20]
            if not name:
                messages.error(request, 'Give the school year a name, e.g. "2027/2028".')
                return redirect("manage:calendar")
            session, made = Session.objects.get_or_create(name=name)
            messages.success(request, f"School year {name} {'added' if made else 'is already there'}. Set its terms below.")
        elif action == "save_term" and session:
            _save_term(request, session)
        return redirect(f"{reverse('manage:calendar')}?year={session.pk if session else ''}")

    terms = {t.number: t for t in session.terms.all()} if session else {}
    rows = []
    for number, label in TERM_CHOICES:
        term = terms.get(number)
        rows.append({
            "number": number, "label": label, "term": term,
            "weeks": weeks_in(term) if term else 12,
            "break_after": break_after_week(term) if term else 6,
            "strip": week_starts(term) if term else [],
        })
    return render(request, "manage/calendar.html", _base_context(
        request, "calendar", sessions=sessions, session=session, rows=rows, max_weeks=MAX_WEEKS,
    ))


def _save_term(request, session):
    number = request.POST.get("number", "")
    try:
        number = int(number)
        starts = date.fromisoformat(request.POST.get("starts", ""))
        weeks = int(request.POST.get("weeks", "0"))
        break_after = int(request.POST.get("break_after") or 0)
    except ValueError:
        messages.error(request, "Give the first day, and the weeks as whole numbers.")
        return
    if number not in dict(TERM_CHOICES) or not 1 <= weeks <= MAX_WEEKS:
        messages.error(request, f"A term has 1 to {MAX_WEEKS} teaching weeks.")
        return
    if starts.weekday() != 0:
        messages.info(request, "Tip: terms are easiest to follow when they start on a Monday.")
    ends, break_starts, break_ends = dates_from_weeks(starts, weeks, break_after)
    Term.objects.update_or_create(
        session=session, number=number,
        defaults={"starts": starts, "ends": ends, "break_starts": break_starts, "break_ends": break_ends},
    )
    label = dict(TERM_CHOICES)[number]
    messages.success(request, f"{label} {session}: {starts:%d %b} to {ends:%d %b %Y}, {weeks} teaching weeks"
                              + (f", break after week {break_after}." if break_starts else ", no break."))
