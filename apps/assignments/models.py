"""
An Assignment is a piece of work a teacher sets one or more of their
classes, with a due date: an EchoSpell group, a Learning Modules day, a
44 Academy or Tricks lesson, or a test. Nobody ticks it off: a pupil has
done it when the site already says they've finished that work
(apps/assignments/progress.py).
"""

from django.conf import settings
from django.db import models
from django.urls import reverse


class Assignment(models.Model):
    class Kind(models.TextChoices):
        GROUP = "group", "EchoSpell group"
        MODULE_DAY = "module_day", "Learning Modules day"
        SOUND = "sound", "44 Academy lesson"
        TRICK = "trick", "Tricks to Sound Fluent lesson"
        TEST = "test", "Test"

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="assignments")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="assignments_set")
    classes = models.ManyToManyField("schools.SchoolClass", related_name="assignments")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    group = models.ForeignKey("echospell.Group", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    module_day = models.ForeignKey("learning_modules.Day", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    lesson = models.ForeignKey("book.Sound", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
                               help_text="A 44 Academy or Tricks to Sound Fluent lesson.")
    assessment = models.ForeignKey("assessments.Assessment", on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="+")
    note = models.CharField(max_length=300, blank=True, help_text="Optional: a word for your pupils.")
    due_on = models.DateField("due")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_on", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def work(self):
        return {self.Kind.GROUP: self.group, self.Kind.MODULE_DAY: self.module_day, self.Kind.SOUND: self.lesson,
                self.Kind.TRICK: self.lesson, self.Kind.TEST: self.assessment}.get(self.kind)

    @property
    def title(self):
        work = self.work
        if work is None:
            return "Assignment"
        if self.kind == self.Kind.GROUP:
            return f"EchoSpell {work.level.name}, Group {work.number}" + (f": {work.title}" if work.title and work.title != f"Group {work.number}" else "")
        if self.kind == self.Kind.MODULE_DAY:
            return f"{work.week.term.module.name}: {work.week.display_name}, {work.get_day_name_display()}"
        if self.kind in (self.Kind.SOUND, self.Kind.TRICK):
            return f"{'44 Academy' if self.kind == self.Kind.SOUND else 'Tricks'}: {work.name}"
        return work.title

    @property
    def url(self):
        """Where pupils go to do it."""
        work = self.work
        if work is None:
            return ""
        if self.kind == self.Kind.GROUP:
            return reverse("echospell:group_detail", args=[work.level.slug, work.slug])
        if self.kind == self.Kind.MODULE_DAY:
            week = work.week
            return reverse("learning_modules:day_detail", args=[week.term.module.slug, week.term.slug, week.slug, work.day_name])
        if self.kind == self.Kind.SOUND:
            return reverse("book:sound_detail", args=[work.slug])
        if self.kind == self.Kind.TRICK:
            return reverse("tricks:lesson", args=[work.slug])
        return reverse("assessments:detail", args=[work.slug])
