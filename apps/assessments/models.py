"""
Assessments — the tests learners take to show what they can do.

Four kinds, each a different experience rather than a different model:

  Practice quiz        untimed, try as often as you like, each answer
                       marked the moment you check it
  Timed test           a countdown the server enforces, answers saved as
                       you go, one submission, limited attempts
  Speaking assessment  record your answers; a teacher marks them against
                       a pronunciation rubric
  Placement test       questions tagged by level; the result recommends
                       the EchoSpell level to start at

An Assessment holds Questions. Each time someone sits it, an Attempt
records their Answers. Objective answers are marked by the same rules
as EchoSpell activities (apps.echospell.marking); spoken answers wait
for a person.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.book.models import AudioContent
from apps.echospell.models import LEVEL_NAME_CHOICES

LEVEL_ORDER = [value for value, _ in LEVEL_NAME_CHOICES]


def _lines(raw):
    return [line.strip() for line in str(raw or "").replace("\r\n", "\n").split("\n") if line.strip()]


def grade_for(percent):
    """The grade band a percentage falls in."""
    if percent >= 85:
        return "Excellent"
    if percent >= 70:
        return "Good"
    if percent >= 50:
        return "Needs practice"
    return "Repeat"


class Assessment(models.Model):
    class Kind(models.TextChoices):
        PRACTICE = "practice", "Practice quiz"
        TIMED = "timed", "Timed test"
        SPEAKING = "speaking", "Speaking assessment"
        PLACEMENT = "placement", "Placement test"

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PRACTICE)
    summary = models.CharField(max_length=255, blank=True, help_text="One line shown in the list.")
    instructions = models.TextField(blank=True, help_text="Shown before the learner starts.")
    level = models.CharField(
        max_length=100, choices=LEVEL_NAME_CHOICES, blank=True,
        help_text="The level this is aimed at. Leave blank for a placement test.",
    )
    time_limit_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Required for a timed test; optional for a placement test.",
    )
    pass_mark = models.PositiveIntegerField(default=70, help_text="Percentage needed to pass.")
    max_attempts = models.PositiveIntegerField(
        default=0, help_text="How many times a learner may sit it. 0 means no limit.",
    )
    shuffle_questions = models.BooleanField(
        default=True, help_text="Give each attempt its own question order.",
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "assessment"
            slug, i = base, 1
            while Assessment.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def clean(self):
        if self.kind == self.Kind.TIMED and not self.time_limit_minutes:
            raise ValidationError({"time_limit_minutes": "A timed test needs a time limit."})

    @property
    def is_timed(self):
        return bool(self.time_limit_minutes) and self.kind in (self.Kind.TIMED, self.Kind.PLACEMENT)

    @property
    def is_practice(self):
        return self.kind == self.Kind.PRACTICE


class Question(AudioContent):
    class Type(models.TextChoices):
        CHOICE = "choice", "Multiple choice"
        LISTEN = "listen", "Listen and choose"
        TRANSCRIBE = "transcribe", "Type the transcription"
        SPELL = "spell", "Type the word"
        SPEAK = "speak", "Speak and record"

    OBJECTIVE_TYPES = {Type.CHOICE, Type.LISTEN, Type.TRANSCRIBE, Type.SPELL}
    CHOICE_TYPES = {Type.CHOICE, Type.LISTEN}

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="questions")
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.CHOICE)
    prompt = models.TextField(help_text="The question, e.g. Which is the correct transcription of CHURCH?")
    word = models.CharField(
        max_length=100, blank=True,
        help_text="Optional word shown large with the question, e.g. THINK.",
    )
    image = models.ImageField(upload_to="assessments/images/%Y/%m/", blank=True)
    options = models.TextField(
        blank=True, help_text="For multiple choice and listening questions — one option per line.",
    )
    answer = models.CharField(
        max_length=255, blank=True,
        help_text="The correct answer. For multiple choice it must match an option exactly. "
                  "Separate equally correct answers with |",
    )
    explanation = models.TextField(blank=True, help_text="Why that's the answer — shown once they've answered.")
    points = models.PositiveIntegerField(default=1)
    level = models.CharField(
        max_length=100, choices=LEVEL_NAME_CHOICES, blank=True,
        help_text="For placement tests: the level this question checks.",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.prompt[:70]

    @property
    def option_list(self):
        return _lines(self.options)

    @property
    def is_objective(self):
        return self.type in self.OBJECTIVE_TYPES

    @property
    def first_answer(self):
        return next((part.strip() for part in self.answer.split("|") if part.strip()), "")

    def clean(self):
        errors = {}
        if self.type in self.CHOICE_TYPES:
            options = self.option_list
            if len(options) < 2:
                errors["options"] = "Give at least two options, one per line."
            elif self.answer.strip() not in options:
                errors["answer"] = "The answer must match one of the options exactly."
        if self.type in (self.Type.TRANSCRIBE, self.Type.SPELL) and not self.answer.strip():
            errors["answer"] = "This question type needs an answer to mark against."
        if self.type == self.Type.LISTEN and not (self.audio_file or self.audio_url):
            errors["audio_file"] = "A listening question needs audio to listen to."
        if errors:
            raise ValidationError(errors)


RUBRIC_CRITERIA = [
    ("sound", "Correct sounds"),
    ("stress", "Word stress"),
    ("articulation", "Clear articulation"),
    ("pace", "Natural pace"),
    ("rhythm", "Rhythm and flow"),
]
RUBRIC_SCALE = [(n, str(n)) for n in range(1, 6)]
RUBRIC_MAX = len(RUBRIC_CRITERIA) * 5


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        SUBMITTED = "submitted", "Marked automatically"
        AWAITING = "awaiting", "Waiting for marking"
        MARKED = "marked", "Marked by a teacher"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assessment_attempts")
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="attempts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    question_order = models.JSONField(default=list, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    score = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0"))
    max_score = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0"))
    percent = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    grade = models.CharField(max_length=30, blank=True)
    recommended_level = models.CharField(max_length=100, blank=True)

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    marked_at = models.DateTimeField(null=True, blank=True)
    feedback = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.user} — {self.assessment} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status == self.Status.IN_PROGRESS

    def ordered_questions(self):
        questions = {q.pk: q for q in self.assessment.questions.all()}
        ordered = [questions[pk] for pk in self.question_order if pk in questions]
        # Questions added after the attempt began still belong on the paper.
        ordered += [q for pk, q in questions.items() if pk not in self.question_order]
        return ordered


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    given = models.TextField(blank=True)
    recording = models.FileField(upload_to="assessments/recordings/%Y/%m/", blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    points_awarded = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    # When a practice answer was checked — after that it is locked.
    checked_at = models.DateTimeField(null=True, blank=True)

    sound = models.PositiveSmallIntegerField(choices=RUBRIC_SCALE, null=True, blank=True)
    stress = models.PositiveSmallIntegerField(choices=RUBRIC_SCALE, null=True, blank=True)
    articulation = models.PositiveSmallIntegerField(choices=RUBRIC_SCALE, null=True, blank=True)
    pace = models.PositiveSmallIntegerField(choices=RUBRIC_SCALE, null=True, blank=True)
    rhythm = models.PositiveSmallIntegerField(choices=RUBRIC_SCALE, null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        unique_together = ("attempt", "question")

    def __str__(self):
        return f"{self.attempt} — Q{self.question_id}"

    @property
    def rubric_rows(self):
        return [(label, getattr(self, field)) for field, label in RUBRIC_CRITERIA]

    @property
    def is_rubric_complete(self):
        return all(getattr(self, field) for field, _ in RUBRIC_CRITERIA)
