"""
The school year on Diction Masters: the term calendar, the scheme of work
for each level, how a term's tests are weighted and graded, and the
report cards that come out of them.

    Session, Term       the platform calendar — "2026/2027", its First,
                        Second and Third Term dates and mid-term breaks;
                        set by staff in the control room
    SchoolTermDates     one school's own dates for a term, when it resumes
                        on a different day (set by the school admin)
    SchemeWeek          what a level does in one week of a term, pointing
                        at content the site already has; staff only
    Grading             the CA / exam weights and grade boundaries (one row)
    ReportCard          a student's term: scores, grade, days practised and
                        the teacher's comment, frozen when the school
                        admin publishes it

Where today falls in the year is worked out in calendar.py, a term's
results in results.py.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.echospell.models import LEVEL_NAME_CHOICES

TERM_CHOICES = [(1, "First Term"), (2, "Second Term"), (3, "Third Term")]
WEEK_CHOICES = [(n, f"Week {n}") for n in range(1, 15)]


class _Dates(models.Model):
    """A term's dates: when it starts and ends, and an optional break."""

    starts = models.DateField()
    ends = models.DateField()
    break_starts = models.DateField("Mid-term break starts", null=True, blank=True)
    break_ends = models.DateField("Mid-term break ends", null=True, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.starts and self.ends and self.ends < self.starts:
            raise ValidationError({"ends": "A term can't end before it starts."})
        if bool(self.break_starts) != bool(self.break_ends):
            raise ValidationError({"break_ends": "Give both break dates, or neither."})
        if self.break_starts and not (self.starts <= self.break_starts <= self.break_ends <= self.ends):
            raise ValidationError({"break_starts": "The break must fall inside the term."})


class Session(models.Model):
    name = models.CharField(max_length=20, unique=True, help_text='The school year, e.g. "2026/2027".')

    class Meta:
        ordering = ["-name"]
        verbose_name = "school year"

    def __str__(self):
        return self.name


class Term(_Dates):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="terms")
    number = models.PositiveSmallIntegerField(choices=TERM_CHOICES)

    class Meta:
        ordering = ["starts"]
        constraints = [models.UniqueConstraint(fields=["session", "number"], name="one_term_number_per_session")]

    def __str__(self):
        return f"{self.get_number_display()} {self.session}"


class SchoolTermDates(_Dates):
    """A school that resumes or breaks on other days than the platform's."""

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="term_dates")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="school_dates")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school", "term"], name="one_dates_per_school_term")]
        verbose_name = "school term dates"
        verbose_name_plural = "school term dates"

    def __str__(self):
        return f"{self.school}: {self.term}"


class SchemeWeek(models.Model):
    """One week of the scheme of work for one level — the same every year,
    so it is tied to a term number, not a dated term."""

    level = models.CharField(max_length=100, choices=LEVEL_NAME_CHOICES)
    term = models.PositiveSmallIntegerField(choices=TERM_CHOICES)
    week = models.PositiveSmallIntegerField(choices=WEEK_CHOICES)
    title = models.CharField(max_length=150, help_text='The week\'s topic, e.g. "The /θ/ and /ð/ sounds".')
    notes = models.TextField(blank=True, help_text="Short notes for the teacher: what to teach and how.")
    groups = models.ManyToManyField(
        "echospell.Group", blank=True, related_name="scheme_weeks",
        help_text="EchoSpell groups for this week, in the order to do them.",
    )
    module_week = models.ForeignKey(
        "learning_modules.Week", null=True, blank=True, on_delete=models.SET_NULL, related_name="scheme_weeks",
        help_text="A Learning Modules week to work through.",
    )
    dialogue_week = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=WEEK_CHOICES,
        help_text="The Conversational Dialogue week for this level and term.",
    )
    assessment = models.ForeignKey(
        "assessments.Assessment", null=True, blank=True, on_delete=models.SET_NULL, related_name="scheme_weeks",
        help_text="A test this week, e.g. a CA test.",
    )

    class Meta:
        ordering = ["level", "term", "week"]
        constraints = [models.UniqueConstraint(fields=["level", "term", "week"], name="one_scheme_week")]
        verbose_name = "scheme of work week"

    def __str__(self):
        return f"{self.level}, {self.get_term_display()}, Week {self.week}: {self.title}"


class Grading(models.Model):
    """How a term's tests make a report card. One row (load())."""

    ca1_weight = models.PositiveSmallIntegerField("CA 1 counts for (%)", default=20)
    ca2_weight = models.PositiveSmallIntegerField("CA 2 counts for (%)", default=20)
    exam_weight = models.PositiveSmallIntegerField("Exam counts for (%)", default=60)
    a_from = models.PositiveSmallIntegerField("A from", default=70)
    b_from = models.PositiveSmallIntegerField("B from", default=60)
    c_from = models.PositiveSmallIntegerField("C from", default=50)
    d_from = models.PositiveSmallIntegerField("D from", default=45)
    e_from = models.PositiveSmallIntegerField("E from", default=40)
    pass_mark = models.PositiveSmallIntegerField(
        "Promote from (%)", default=50, help_text="A session average from this mark is suggested for promotion.",
    )

    class Meta:
        verbose_name = "grading"
        verbose_name_plural = "grading"

    def __str__(self):
        return "Grading"

    def clean(self):
        if self.ca1_weight + self.ca2_weight + self.exam_weight != 100:
            raise ValidationError("CA 1, CA 2 and the exam must add up to 100%.")
        if not (self.a_from > self.b_from > self.c_from > self.d_from > self.e_from):
            raise ValidationError("Each grade must start above the next one down.")

    @classmethod
    def load(cls):
        found, _ = cls.objects.get_or_create(pk=1)
        return found

    def grade(self, total):
        if total is None:
            return ""
        for letter, start in (("A", self.a_from), ("B", self.b_from), ("C", self.c_from),
                              ("D", self.d_from), ("E", self.e_from)):
            if total >= start:
                return letter
        return "F"


class ReportCard(models.Model):
    """A student's term. Before it's published only the teacher's comment
    is kept here and the scores are worked out live; publishing freezes
    the scores as they were."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="report_cards")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="report_cards")
    level = models.CharField(max_length=100, blank=True)
    ca1 = models.PositiveSmallIntegerField(null=True, blank=True)
    ca2 = models.PositiveSmallIntegerField(null=True, blank=True)
    exam = models.PositiveSmallIntegerField(null=True, blank=True)
    total = models.PositiveSmallIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=2, blank=True)
    days_practised = models.PositiveSmallIntegerField(default=0)
    teacher_comment = models.TextField(blank=True)
    comment_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")

    class Meta:
        ordering = ["-term__starts"]
        constraints = [models.UniqueConstraint(fields=["student", "term"], name="one_report_card_per_term")]

    def __str__(self):
        return f"{self.student} — {self.term}"
