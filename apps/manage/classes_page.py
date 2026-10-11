"""
The control room's Classes & grades page.

    - the grades (apps/schools/grades.py): each stage, its grades and the
      content level each follows, with how many classes use it, and an Edit
      page for each (grade_edit) to rename it or change its level;
    - every school's classes, newest school year first, with their students
      and class teacher, or one school's (?school=), linking to each class's
      edit form (the "classes" screen) and to add one.

A few queries for the whole page, whatever the number of schools.
"""

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from apps.accounts.models import User
from apps.echospell.models import LEVEL_NAME_CHOICES
from apps.schools import classes as school_classes
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
    stages = [{"label": label, "grades": [{"grade": g, "classes": used.get(g.key, 0),
                                           "changed": (g.label, g.level) != (grades.DEFAULTS[g.key].label,
                                                                            grades.DEFAULTS[g.key].level)}
                                          for g in grades.current() if g.stage == stage]}
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


class GradeForm(forms.Form):
    label = forms.CharField(label="Name", max_length=40)
    level = forms.ChoiceField(label="Content level it follows", choices=LEVEL_NAME_CHOICES)

    def __init__(self, *args, grade, **kwargs):
        super().__init__(*args, **kwargs)
        self.grade = grade
        for field in self.fields.values():
            field.widget.attrs["class"] = "cr-input" + (" cr-select" if isinstance(field, forms.ChoiceField) else "")

    def clean_label(self):
        label = " ".join(self.cleaned_data["label"].split())
        taken = {g.label.lower() for g in grades.current() if g.key != self.grade.key}
        if label.lower() in taken:
            raise forms.ValidationError(f"Another grade is already called “{label}”.")
        return label


@staff_only
def grade_edit(request, key):
    """Rename one grade and choose the content level it follows."""
    grade = grades.by_key().get(key) or _not_found()
    default = grades.DEFAULTS[key]
    in_grade = User.objects.filter(role=User.Role.STUDENT, is_active=True, school_class__grade=key)
    form = GradeForm(request.POST or None, grade=grade, initial={"label": grade.label, "level": grade.level})
    if request.method == "POST":
        if request.POST.get("action") == "reset":
            moved = school_classes.change_grade(key, default.label, default.level)
            messages.success(request, f"{default.label} is back to its own name and {default.level}."
                                      + (f" {moved} student{'s' if moved != 1 else ''} moved to {default.level}." if moved else ""))
            return redirect("manage:classes_overview")
        if form.is_valid():
            moved = school_classes.change_grade(key, form.cleaned_data["label"], form.cleaned_data["level"])
            messages.success(request, f"Saved: {form.cleaned_data['label']} follows {form.cleaned_data['level']}."
                                      + (f" {moved} student{'s' if moved != 1 else ''} now learn{'' if moved != 1 else 's'} "
                                         f"{form.cleaned_data['level']}'s lessons." if moved else ""))
            return redirect("manage:classes_overview")
    return render(request, "manage/grade_edit.html", _base_context(
        request, "classes-overview", grade=grade, default=default, form=form,
        changed=(grade.label, grade.level) != (default.label, default.level),
        stage=grades.STAGE_LABELS[grade.stage], students=in_grade.count(),
        classes=SchoolClass.objects.filter(grade=key).count(),
    ))


def _not_found():
    from django.http import Http404

    raise Http404("No such grade.")
