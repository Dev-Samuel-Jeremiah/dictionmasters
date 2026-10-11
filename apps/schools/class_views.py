"""
The school admin's Classes pages.

    classes        every class this school year, by stage, with how many
                   students each has, who teaches it and its sign-up link;
                   and a form to add one
    class_detail   one class: rename it, change its grade or teachers,
                   move students to another class, or delete it once empty

Moving a student to a class takes them to that grade's level (what they
can open follows it) and goes in the school's level history. A class with
students can't be deleted. Classes themselves live in apps/schools/classes.py.
"""

from django import forms
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from . import classes as school_classes
from . import grades
from .models import SchoolClass


class ClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ["grade", "name", "class_teacher", "teachers"]
        labels = {"name": "Class name", "class_teacher": "Class teacher", "teachers": "Other teachers"}
        help_texts = {"name": 'Optional, e.g. "Gold" or "A". Leave blank if the grade has one class.'}
        widgets = {"teachers": forms.CheckboxSelectMultiple}

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        teachers = User.objects.filter(school=school, role=User.Role.TEACHER, is_active=True).order_by("first_name", "last_name")
        self.fields["class_teacher"].queryset = teachers
        self.fields["class_teacher"].empty_label = "No class teacher yet"
        self.fields["class_teacher"].label_from_instance = lambda u: u.get_full_name() or u.login_name
        self.fields["teachers"].queryset = teachers
        self.fields["teachers"].label_from_instance = lambda u: u.get_full_name() or u.login_name
        self.fields["teachers"].required = False
        self.fields["grade"].choices = grades.grade_choices()
        for name in ("grade", "name", "class_teacher"):
            self.fields[name].widget.attrs["class"] = "field-input"

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean(self):
        cleaned = super().clean()
        grade, name = cleaned.get("grade"), cleaned.get("name", "")
        session = self.instance.session if self.instance.pk else school_classes.school_year(self.school)
        clash = SchoolClass.objects.filter(school=self.school, session=session, grade=grade, name__iexact=name)
        if grade and clash.exclude(pk=self.instance.pk).exists():
            self.add_error("name", f"There's already a {grades.label_for(grade)} {name}".strip()
                           + " class this year. Give this one another name.")
        return cleaned

    def save(self, commit=True):
        found = super().save(commit=False)
        if not found.pk:
            found.school, found.session = self.school, school_classes.school_year(self.school)
        found.save()
        self.save_m2m()
        if found.class_teacher_id:
            found.teachers.add(found.class_teacher)          # the class teacher teaches it too
        return found


def _join_link(request, school_class):
    return request.build_absolute_uri(reverse("accounts:register_student")) + \
        f"?school={school_class.school.code}&class={school_class.pk}"


@role_required(User.Role.SCHOOL_ADMIN)
def classes(request):
    school = request.user.school
    form = ClassForm(request.POST or None, school=school)
    if request.method == "POST" and form.is_valid():
        made = form.save()
        messages.success(request, f"{made.display_name} added. Share its sign-up link so its students join it.")
        return redirect("schools:class_detail", pk=made.pk)
    found = school_classes.this_year(school)
    counts = dict(User.objects.filter(school_class__in=found, is_active=True).values("school_class")
                  .annotate(n=Count("id")).values_list("school_class", "n"))
    teachers = {}
    for row in SchoolClass.teachers.through.objects.filter(schoolclass__in=found).select_related("user"):
        teachers.setdefault(row.schoolclass_id, []).append(row.user)
    stages = []
    for stage, label in grades.STAGES:
        rows = [{"class": c, "students": counts.get(c.pk, 0), "teachers": teachers.get(c.pk, []),
                 "link": _join_link(request, c)}
                for c in found if grades.DEFAULTS[c.grade].stage == stage]
        if rows:
            stages.append({"label": label, "rows": rows})
    unplaced = User.objects.filter(school=school, role=User.Role.STUDENT, is_active=True, school_class__isnull=True)
    return render(request, "schools/classes.html", {
        "school": school, "stages": stages, "form": form, "total": len(found),
        "session": school_classes.school_year(school), "unplaced": unplaced.count(),
    })


@role_required(User.Role.SCHOOL_ADMIN)
def class_detail(request, pk):
    school = request.user.school
    found = get_object_or_404(SchoolClass, pk=pk, school=school)
    students = User.objects.filter(school_class=found, is_active=True).order_by("first_name", "last_name")
    form = ClassForm(instance=found, school=school)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            form = ClassForm(request.POST, instance=found, school=school)
            if form.is_valid():
                form.save()
                messages.success(request, f"{found.display_name} saved.")
                return redirect("schools:class_detail", pk=found.pk)
        elif action == "move":
            target = SchoolClass.objects.filter(school=school, pk=request.POST.get("to") or 0).first()
            chosen = list(students.filter(pk__in=request.POST.getlist("students")))
            if target is None or not chosen:
                messages.error(request, "Tick the students to move and choose the class to move them to.")
            else:
                moved = school_classes.move(request.user, chosen, target)
                messages.success(request, f"{moved} student{'s' if moved != 1 else ''} moved to {target.display_name}.")
            return redirect("schools:class_detail", pk=found.pk)
        elif action == "delete":
            if students.exists() or found.students.exists():
                messages.error(request, f"{found.display_name} still has students. Move them to another class first.")
                return redirect("schools:class_detail", pk=found.pk)
            name = found.display_name
            found.delete()
            messages.success(request, f"{name} deleted.")
            return redirect("schools:classes")
    others = [c for c in school_classes.this_year(school) if c.pk != found.pk]
    return render(request, "schools/class_detail.html", {
        "school": school, "class": found, "students": students, "form": form, "others": others,
        "link": _join_link(request, found), "teachers": list(found.teachers.all()),
    })
