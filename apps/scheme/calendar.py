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
