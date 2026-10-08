"""
Where today falls in the school year.

    terms_for(school)          every term with this school's dates (its own
                               where it set them, the platform's otherwise)
    where_we_are(user, today)  {"term", "week", "state", "label", ...}

A term's weeks are counted from its first day, seven days a week, with
the mid-term break left out: the week after a one-week break is the next
week, not one further on. "state" is "term", "break" (mid-term) or
"holiday" (between terms, when "next" is the term to come).
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import SchoolTermDates, Term


class _Dated:
    """A term as one school keeps it: the platform term, with that
    school's dates laid over it when it has its own."""

    def __init__(self, term, own=None):
        self.term = term
        source = own or term
        self.starts, self.ends = source.starts, source.ends
        self.break_starts, self.break_ends = source.break_starts, source.break_ends

    @property
    def number(self):
        return self.term.number

    def __str__(self):
        return str(self.term)


def terms_for(school):
    """Every term in date order, with `school`'s own dates where it has
    them. Two small queries."""
    own = {}
    if school is not None:
        own = {d.term_id: d for d in SchoolTermDates.objects.filter(school=school)}
    terms = [_Dated(t, own.get(t.pk)) for t in Term.objects.select_related("session")]
    return sorted(terms, key=lambda t: t.starts)


def week_of(dated, day):
    """The week number `day` falls in, the break left out."""
    days = (day - dated.starts).days
    if dated.break_starts and day > dated.break_ends:
        days -= (dated.break_ends - dated.break_starts).days + 1
    return days // 7 + 1


def where_we_are(user, today=None):
    """Today's place in the school year for this person's school (or the
    platform's calendar), or state "none" when no calendar is set."""
    today = today or timezone.localdate()
    terms = terms_for(getattr(user, "school", None))
    for dated in terms:
        if dated.starts <= today <= dated.ends:
            if dated.break_starts and dated.break_starts <= today <= dated.break_ends:
                return {"state": "break", "term": dated, "week": None,
                        "label": f"{dated.term.get_number_display()}: mid-term break"}
            week = week_of(dated, today)
            return {"state": "term", "term": dated, "week": week,
                    "label": f"{dated.term.get_number_display()}, Week {week}"}
    upcoming = next((t for t in terms if t.starts > today), None)
    if upcoming:
        return {"state": "holiday", "term": None, "week": None, "next": upcoming,
                "label": f"Holiday. {upcoming.term.get_number_display()} starts {upcoming.starts:%A %d %B}."}
    return {"state": "none", "term": None, "week": None, "label": ""}


def last_term(user, today=None):
    """The term that's on, or the latest one that has ended: the term
    report cards are being written for."""
    today = today or timezone.localdate()
    started = [t for t in terms_for(getattr(user, "school", None)) if t.starts <= today]
    return started[-1] if started else None


def weeks_in(dated):
    """How many teaching weeks the term has."""
    return week_of(dated, dated.ends)


def term_window(dated, grace_days=21):
    """The moments a term's tests count from and to: its first day to its
    last, plus time for spoken answers to be marked."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(dated.starts, time.min), tz)
    end = timezone.make_aware(datetime.combine(dated.ends + timedelta(days=grace_days), time.max), tz)
    return start, end


def dates_from_weeks(starts, weeks, break_after=0, break_weeks=1):
    """A term's other dates from its first day, how many teaching weeks it
    has, and the week its mid-term break follows (0 for none): (ends,
    break_starts, break_ends). Starting on a Monday, the term ends on a
    Friday and the break runs Monday to Friday."""
    has_break = 0 < break_after < weeks and break_weeks > 0
    gap = timedelta(weeks=break_weeks) if has_break else timedelta(0)
    ends = starts + timedelta(weeks=weeks) + gap - timedelta(days=3)
    if not has_break:
        return ends, None, None
    break_starts = starts + timedelta(weeks=break_after)
    return ends, break_starts, break_starts + gap - timedelta(days=3)


def week_starts(dated):
    """[(week number, its first day)] for every teaching week of a term,
    for showing the term as a strip of weeks."""
    found, day = [], dated.starts
    for number in range(1, weeks_in(dated) + 1):
        if dated.break_starts and dated.break_starts <= day <= dated.break_ends:
            day = dated.break_ends + timedelta(days=3)
        found.append((number, day))
        day += timedelta(weeks=1)
    return found


def break_after_week(dated):
    """The teaching week the mid-term break follows, or 0."""
    if not dated.break_starts:
        return 0
    return week_of(dated, dated.break_starts - timedelta(days=1))
