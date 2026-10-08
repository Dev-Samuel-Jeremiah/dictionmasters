"""
The scheme of work, week by week.

    this_week(user, level)  for a teacher: where the term is, this week's
                            SchemeWeek for the level, and the term's weeks
    scheme_lesson(user)     for a pupil at a school: the first thing in this
                            week's scheme not done yet, for Today's lesson
                            (apps/accounts/dashboard_data.todays_lesson)

A pupil's scheme lesson is the week's EchoSpell groups in number order,
then its Learning Modules week's days, then its test if it's open and
not yet sat. Nothing in the scheme for this week, or nothing left in it,
gives None and Today's lesson carries on as before.
"""

from django.urls import reverse
from django.utils import timezone

from apps.assessments.models import Attempt
from apps.echospell.models import GroupProgress
from apps.learning_modules.models import DayProgress

from .calendar import where_we_are, weeks_in
from .models import SchemeWeek


def this_week(user, level, today=None):
    place = where_we_are(user, today)
    if place["state"] != "term" or not level:
        return {"place": place, "week": None, "strip": []}
    number = place["term"].number
    weeks = {w.week: w for w in SchemeWeek.objects.filter(level=level, term=number)}
    strip = [{"number": n, "scheme": weeks.get(n), "is_now": n == place["week"]}
             for n in range(1, weeks_in(place["term"]) + 1)]
    return {"place": place, "week": weeks.get(place["week"]), "strip": strip}


def scheme_lesson(user, today=None):
    if not (getattr(user, "is_student", False) and user.school_id and user.level):
        return None
    place = where_we_are(user, today)
    if place["state"] != "term":
        return None
    week = (
        SchemeWeek.objects.filter(level=user.level, term=place["term"].number, week=place["week"])
        .select_related("module_week__term__module", "assessment").first()
    )
    if week is None:
        return None
    label = f"This week: {week.title}"

    done_groups = set(GroupProgress.objects.filter(user=user).values_list("group_id", flat=True))
    for group in week.groups.filter(level__is_published=True).select_related("level").order_by("number"):
        if group.pk not in done_groups:
            return {"kind": "echospell", "label": label, "percent": None,
                    "title": f"EchoSpell: {group.level.name}, Group {group.number}",
                    "detail": place["label"],
                    "url": reverse("echospell:group_detail", args=[group.level.slug, group.slug])}

    if week.module_week_id and week.module_week.term.module.is_published:
        done_days = set(DayProgress.objects.filter(user=user).values_list("day_id", flat=True))
        mweek, mterm = week.module_week, week.module_week.term
        for day in mweek.days.filter(is_published=True).order_by("order", "id"):
            if day.pk not in done_days:
                return {"kind": "modules", "label": label, "percent": None,
                        "title": f"{mterm.module.name}: {day.get_day_name_display()}",
                        "detail": place["label"],
                        "url": reverse("learning_modules:day_detail",
                                       args=[mterm.module.slug, mterm.slug, mweek.slug, day.day_name])}

    test = week.assessment
    if (test and test.is_published and test.window(timezone.now()) == "open"
            and not Attempt.objects.filter(user=user, assessment=test).exclude(status=Attempt.Status.IN_PROGRESS).exists()):
        return {"kind": "assessment", "label": label, "percent": None,
                "title": test.title, "detail": f"{test.get_kind_display()} · {place['label']}",
                "url": reverse("assessments:detail", args=[test.slug])}
    return None
