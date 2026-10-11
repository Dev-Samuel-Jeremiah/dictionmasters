"""
Setting an assignment: which classes, what work, when it's due.

The work list is built from the teacher's classes' levels (an EchoSpell
group or a Learning Modules day of that level, a 44 Academy or Tricks
lesson where that grade may open it, a test for that level), and checked
again against every class chosen, so a Grade 1 class can't be set a
Grade 3 group, or the 44 Academy, which starts at Grade 3. Values are
"<kind>:<pk>".
"""

from django import forms
from django.utils import timezone

from apps.accounts.access import tool_levels, unpack_levels
from apps.schools.grades import label_for_level

from .models import Assignment

K = Assignment.Kind


def _tool_open(tool, level, kept):
    levels = kept.get(tool)
    return not levels or level in levels


def work_choices(levels):
    """[(group label, [(value, label)])] of everything these levels can be set."""
    from apps.assessments.models import Assessment
    from apps.book.models import ACADEMY, TRICKS
    from apps.echospell.models import Group
    from apps.learning_modules.models import Day
    from apps.tricks.progress import lessons_in_order

    levels = sorted(set(levels))
    kept = tool_levels()
    out = []
    groups = (Group.objects.filter(level__name__in=levels, level__is_published=True)
              .select_related("level").order_by("level__order", "level__name", "number"))
    out.append(("EchoSpell", [
        (f"{K.GROUP}:{g.pk}", f"{label_for_level(g.level.name)} · Group {g.number}"
                              + (f": {g.title}" if g.title and g.title != f"Group {g.number}" else ""))
        for g in groups]))
    days = (Day.objects.filter(is_published=True, week__term__module__is_published=True)
            .select_related("week__term__module")
            .order_by("week__term__module__order", "week__term__module__name", "week__term__order", "week__term__id",
                      "week__number", "order"))
    out.append(("Learning Modules", [
        (f"{K.MODULE_DAY}:{d.pk}", f"{d.week.term.module.name}: {d.week.term.name}, {d.week.display_name}, {d.get_day_name_display()}")
        for d in days
        if not unpack_levels(d.week.term.module.levels) or set(levels) & set(unpack_levels(d.week.term.module.levels))]))
    if any(_tool_open("book:home", level, kept) for level in levels):
        out.append(("44 Academy", [(f"{K.SOUND}:{s.pk}", s.name) for s in lessons_in_order(ACADEMY)]))
    if any(_tool_open("tricks:home", level, kept) for level in levels):
        out.append(("Tricks to Sound Fluent", [(f"{K.TRICK}:{s.pk}", s.name) for s in lessons_in_order(TRICKS)]))
    tests = Assessment.objects.filter(is_published=True, level__in=levels + [""]).order_by("level", "title")
    out.append(("Tests", [(f"{K.TEST}:{t.pk}", t.title + (f" ({label_for_level(t.level)})" if t.level else "")) for t in tests]))
    return [(label, options) for label, options in out if options]


def _fits(kind, work, level, kept):
    """Can a class on `level` be set this work? (True, "") or (False, why)."""
    if kind == K.GROUP:
        return work.level.name == level, f"it's {label_for_level(work.level.name)} work"
    if kind == K.MODULE_DAY:
        wanted = unpack_levels(work.week.term.module.levels)
        return (not wanted or level in wanted), "that module isn't for their grade"
    if kind == K.SOUND:
        return _tool_open("book:home", level, kept), "their grade doesn't have the 44 Academy"
    if kind == K.TRICK:
        return _tool_open("tricks:home", level, kept), "their grade doesn't have Tricks to Sound Fluent"
    if kind == K.TEST:
        return (not work.level or work.level == level), f"it's a {label_for_level(work.level)} test"
    return False, "it isn't something that can be set"


def resolve(value):
    """(kind, the work) for a "<kind>:<pk>" value, or (None, None)."""
    from apps.assessments.models import Assessment
    from apps.book.models import Sound
    from apps.echospell.models import Group
    from apps.learning_modules.models import Day

    kind, _sep, pk = str(value or "").partition(":")
    model = {K.GROUP: Group, K.MODULE_DAY: Day, K.SOUND: Sound, K.TRICK: Sound, K.TEST: Assessment}.get(kind)
    if model is None or not pk.isdigit():
        return None, None
    return kind, model.objects.filter(pk=int(pk)).first()


class AssignmentForm(forms.Form):
    classes = forms.ModelMultipleChoiceField(queryset=None, widget=forms.CheckboxSelectMultiple,
                                             label="Which classes")
    work = forms.ChoiceField(label="What to do", choices=[])
    due_on = forms.DateField(label="Due", widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(label="A note for your pupils (optional)", max_length=300, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "e.g. Practise the passage aloud twice."}))

    def __init__(self, *args, classes, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed = list(classes)
        self.fields["classes"].queryset = classes
        self.fields["classes"].label_from_instance = lambda c: c.display_name
        self.fields["work"].choices = [("", "Choose the work")] + work_choices([c.level for c in self.allowed])
        for name in ("work", "due_on", "note"):
            self.fields[name].widget.attrs["class"] = "field-input"

    def clean_due_on(self):
        due = self.cleaned_data["due_on"]
        if due < timezone.localdate():
            raise forms.ValidationError("Choose today or a day after.")
        return due

    def clean(self):
        cleaned = super().clean()
        kind, work = resolve(cleaned.get("work"))
        if cleaned.get("work") and work is None:
            self.add_error("work", "Choose the work again.")
            return cleaned
        kept = tool_levels()
        for school_class in cleaned.get("classes") or []:
            ok, why = _fits(kind, work, school_class.level, kept)
            if not ok:
                self.add_error("work", f"{school_class.display_name} can't be set this: {why}.")
        cleaned["kind"], cleaned["target"] = kind, work
        return cleaned

    def save(self, school, teacher):
        data = self.cleaned_data
        field = {K.GROUP: "group", K.MODULE_DAY: "module_day", K.SOUND: "lesson", K.TRICK: "lesson",
                 K.TEST: "assessment"}[data["kind"]]
        made = Assignment.objects.create(school=school, created_by=teacher, kind=data["kind"], due_on=data["due_on"],
                                         note=data["note"], **{field: data["target"]})
        made.classes.set(data["classes"])
        return made


class ChangeForm(forms.ModelForm):
    """Changing an assignment's due date or note."""

    class Meta:
        model = Assignment
        fields = ["due_on", "note"]
        widgets = {"due_on": forms.DateInput(attrs={"type": "date", "class": "field-input"}, format="%Y-%m-%d"),
                   "note": forms.TextInput(attrs={"class": "field-input"})}
        labels = {"note": "A note for your pupils (optional)"}
