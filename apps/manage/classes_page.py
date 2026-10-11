"""
The control room's Classes & grades page.

    - the grades (apps/schools/grades.py): each stage, its grades and the
      content level each follows, with how many classes use it;
    - every school's classes, newest school year first, with their students
      and class teacher, or one school's (?school=), linking to each class's
      edit form (the "classes" screen) and to add one.

A few queries for the whole page, whatever the number of schools.
"""

from django.db.models import Count, Q
from django.shortcuts import render

from apps.schools import grades
from apps.schools.classes import GRADE_ORDER
from apps.schools.models import School, SchoolClass

from .views import _base_context, staff_only

MOST = 400          # classes listed at once without a school chosen


@staff_only
def classes_overview(request):
    schools = list(School.objects.order_by("name").only("pk", "name"))
    chosen = next((s for s in schools if str(s.pk) == request.GET.get("school")), None)

    used = dict(SchoolClass.objects.values_list("grade").annotate(n=Count("pk")))
    stages = [{"label": label, "grades": [{"grade": g, "classes": used.get(g.key, 0)}
                                          for g in grades.GRADES if g.stage == stage]}
              for stage, label in grades.STAGES]

    found = (SchoolClass.objects.select_related("school", "session", "class_teacher")
             .annotate(students_n=Count("students", filter=Q(students__is_active=True))))
    if chosen:
        found = found.filter(school=chosen)
    found = list(found.order_by("school__name", "-session__name")[:MOST])
    found.sort(key=lambda c: (c.school.name.lower(), -(c.session_id or 0), GRADE_ORDER.get(c.grade, 99), c.name.lower()))
    groups = []
    for school_class in found:
        if not groups or groups[-1]["school"].pk != school_class.school_id:
            groups.append({"school": school_class.school, "years": []})
        years = groups[-1]["years"]
        if not years or years[-1]["session"] != school_class.session:
            years.append({"session": school_class.session, "classes": []})
        years[-1]["classes"].append(school_class)

    return render(request, "manage/classes_overview.html", _base_context(
        request, "classes-overview", stages=stages, groups=groups, schools=schools, chosen=chosen,
        total=SchoolClass.objects.count(), capped=not chosen and len(found) >= MOST,
    ))
