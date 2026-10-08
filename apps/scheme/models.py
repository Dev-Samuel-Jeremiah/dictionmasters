"""
The school year on Diction Masters: the term calendar, the scheme of work
for each level, how a term's tests are weighted and graded, and the
report cards that come out of them.

    Session, Term       the platform calendar — "2026/2027", its First,
                        Second and Third Term dates and mid-term breaks;
                        set by staff in the control room
    SchoolTermDates     one school's own dates for a term, when it resumes
                        on a different day (set by the school admin)
    SchemeEntry         the scheme of work: a piece of content a level does
                        in one week of a term, on one day; staff only
    SchemeOpened        a student opened an entry from their scheme
    SchemeChoice        the level's scheme an individual learner follows,
                        at their own pace
    Grading             the CA / exam weights and grade boundaries (one row)
    ReportCard          a student's term: scores, grade, days practised and
                        the teacher's comment, frozen when the school
                        admin publishes it

Where today falls in the year is worked out in calendar.py, what a
student sees and may open in timetable.py, a term's results in results.py.
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


DAY_CHOICES = [
    ("", "Any day this week"),
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
]
DAY_ORDER = [key for key, _label in DAY_CHOICES]


class SchemeEntry(models.Model):
    """One piece of content on the scheme of work: this level does it in
    this week of this term, on this day (or any day that week). The same
    every year, so it is tied to a term number, not a dated term.

    Exactly one of the content fields is filled, the one its `kind` names
    (Daily Practice needs none). apps/scheme/timetable.py turns entries into
    what a student sees and may open."""

    class Kind(models.TextChoices):
        GROUP = "group", "EchoSpell group"
        MODULE_DAY = "module_day", "Learning Modules day"
        DIALOGUE = "dialogue", "Conversational Dialogue"
        SOUND = "sound", "44 Academy sound"
        TRICK = "trick", "Tricks to Sound Fluent lesson"
        CHAPTER = "chapter", "Reading Club chapter"
        RECITAL = "recital", "Assembly Recital"
        LIBRARY = "library", "Diction Library item"
        ASSESSMENT = "assessment", "Assessment"
        DAILY_PRACTICE = "daily_practice", "Daily Practice"

    # The content field each kind fills in.
    FIELD_FOR = {
        Kind.GROUP: "group", Kind.MODULE_DAY: "module_day", Kind.DIALOGUE: "dialogue",
        Kind.SOUND: "sound", Kind.TRICK: "sound", Kind.CHAPTER: "chapter", Kind.RECITAL: "recital",
        Kind.LIBRARY: "library_item", Kind.ASSESSMENT: "assessment", Kind.DAILY_PRACTICE: None,
    }

    level = models.CharField(max_length=100, choices=LEVEL_NAME_CHOICES)
    term = models.PositiveSmallIntegerField(choices=TERM_CHOICES)
    week = models.PositiveSmallIntegerField(choices=WEEK_CHOICES)
    day = models.CharField(max_length=10, choices=DAY_CHOICES, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # A draft (from the scheme builder, apps/scheme/builder.py) is seen and
    # edited in the control room only; publishing makes it the live scheme.
    is_draft = models.BooleanField(default=False)

    group = models.ForeignKey("echospell.Group", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    module_day = models.ForeignKey("learning_modules.Day", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    dialogue = models.ForeignKey("conversational_dialogue.Dialogue", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    sound = models.ForeignKey("book.Sound", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    chapter = models.ForeignKey("reading_club.Chapter", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    recital = models.ForeignKey("assembly_recitals.Recital", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    library_item = models.ForeignKey("diction_library.LibraryItem", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    assessment = models.ForeignKey("assessments.Assessment", null=True, blank=True, on_delete=models.CASCADE, related_name="+")

    class Meta:
        ordering = ["level", "term", "week", "day", "order", "pk"]
        indexes = [models.Index(fields=["level", "term", "week"]), models.Index(fields=["level", "term", "is_draft"])]
        verbose_name = "scheme of work entry"
        verbose_name_plural = "scheme of work entries"

    def __str__(self):
        return f"{self.level}, {self.get_term_display()}, Week {self.week}: {self.title}"

    @property
    def content(self):
        field = self.FIELD_FOR.get(self.kind)
        return getattr(self, field) if field else None

    @property
    def title(self):
        if self.kind == self.Kind.DAILY_PRACTICE:
            return "Daily Practice"
        content = self.content
        if content is None:
            return self.get_kind_display()
        if self.kind == self.Kind.GROUP:
            return f"EchoSpell Group {content.number}"
        if self.kind == self.Kind.MODULE_DAY:
            return f"{content.week.term.module.name}: {content.get_day_name_display()}, {content.week.display_name}"
        if self.kind == self.Kind.SOUND:
            return f"44 Academy: {content.name}"
        if self.kind == self.Kind.TRICK:
            return f"Tricks: {content.name}"
        return str(getattr(content, "title", None) or content)

    def clean(self):
        field = self.FIELD_FOR.get(self.kind)
        filled = [name for name in set(self.FIELD_FOR.values()) if name and getattr(self, f"{name}_id")]
        if field and filled != [field]:
            raise ValidationError(f"Choose the {self.get_kind_display()} this entry is for, and nothing else.")
        if not field and filled:
            raise ValidationError("Daily Practice needs no content chosen.")


class SchemeOpened(models.Model):
    """A student opened a scheme entry from their scheme. For content whose
    tool keeps no record of being done (a recital, a library item, Daily
    Practice), opening it is what counts."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheme_opened")
    entry = models.ForeignKey(SchemeEntry, on_delete=models.CASCADE, related_name="opened")
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "entry"], name="one_opened_per_entry")]


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


class SchemeChoice(models.Model):
    """The scheme an individual learner chose to follow, at their own pace
    (apps/scheme/path.py). Changing it keeps everything they've done."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scheme_choice")
    level = models.CharField(max_length=100, choices=LEVEL_NAME_CHOICES)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} follows the {self.level} scheme"
