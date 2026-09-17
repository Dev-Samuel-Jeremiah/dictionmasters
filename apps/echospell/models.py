"""
EchoSpell — a spelling and phonics programme organised as
Level > Group > Card, where a "card" is one of several reusable
activity types (Spelling, Vocabulary, Transcription, Missing Letter,
Listen & Circle, Look-Listen-Echo, Listen & Number, Puzzle, Passage
Reading, Dialogue).

Rather than one model per activity type, a Category record describes
a *feature* (name, icon, colour, and which content shape it needs —
"words", "passage" or "dialogue") and is assigned to whichever Levels
it applies to. Every group in that level then gets one card per
assigned category — and each of those cards holds its *own* content:
a "words"-kind card is built from CardLesson rows scoped to that
exact (group, category) pair, not a list shared across every category
in the group, so Puzzle and Vocabulary for the same group can carry
entirely different words, audio and video. Passage Reading and
Dialogue still get their own dedicated content shape.

Cards teach; Activities test. An Activity is a scored exercise hung off
a Level (optionally narrowed to one Group), built from ActivityItems
and answered into an ActivityAttempt. Its kind — transcription, sound
sort, read-aloud recording and so on — comes from the catalogue in
activity_kinds.py, and everything auto-markable is marked in
marking.py.
"""

import re

from django.conf import settings
from django.db import models
from django.utils.text import slugify

# Strips a leading list marker from one entered line/segment, so admins
# can type "1. seat", "1) seat", "1 - seat" or just "seat" and all read
# the same — the frontend does its own numbering from the resulting
# order rather than trusting whatever number was typed.
_LIST_MARKER_RE = re.compile(r"^\s*(?:\d+\s*[\.\)\-:]|[-*•])\s*")


def _parse_lines(raw):
    """A textarea of one-per-line entries into a clean list, with any
    leading "1." / "1)" / "-" marker stripped."""
    text = str(raw or "").replace("\r\n", "\n")
    return [cleaned for line in text.split("\n") if (cleaned := _LIST_MARKER_RE.sub("", line).strip())]

LEVEL_NAME_CHOICES = [("Pre-Level", "Pre-Level")] + [
    (f"Level {i}", f"Level {i}") for i in range(1, 13)
]

GROUP_NUMBER_CHOICES = [(i, i) for i in range(1, 51)]

from apps.book.models import AudioContent, VideoContent
from apps.learning_modules.models import COLOR_CHOICES, ICON_CHOICES

from .activity_kinds import ACTIVITY_KIND_CHOICES, MODE_SORT, get_kind

CATEGORY_KIND_CHOICES = [
    ("words", "Word cards"),
    ("passage", "Passage reading"),
    ("dialogue", "Dialogue"),
]


class Category(models.Model):
    """A reusable card/feature type, e.g. "Spelling" or "Missing Letter"."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    kind = models.CharField(
        max_length=20, choices=CATEGORY_KIND_CHOICES, default="words",
        help_text="What content this card needs: a word list, a passage, or a dialogue.",
    )
    description = models.CharField(
        max_length=255, blank=True, help_text="One line shown on the 'choose a card' screen."
    )
    icon = models.CharField(max_length=8, choices=ICON_CHOICES, default="✏️")
    color = models.CharField(max_length=7, choices=COLOR_CHOICES, default="#1B3A6B")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "category"
            slug = base
            i = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Level(models.Model):
    """A class level, e.g. "Pre-Level" or "Level 3"."""

    name = models.CharField(max_length=100, choices=LEVEL_NAME_CHOICES)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    age_range = models.CharField(max_length=100, blank=True, help_text='e.g. "Nursery 1-2"')
    description = models.CharField(max_length=255, blank=True)
    categories = models.ManyToManyField(
        Category, blank=True, related_name="levels",
        help_text="Which cards are available for every group in this level.",
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, help_text="Unpublished levels are hidden from the hub.")

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "level"
            slug = base
            i = 1
            while Level.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Group(models.Model):
    """One numbered group of words within a level, e.g. "Group 5"."""

    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name="groups")
    number = models.PositiveIntegerField(
        choices=GROUP_NUMBER_CHOICES, help_text="Group number within the level, e.g. 1"
    )
    title = models.CharField(max_length=150, blank=True, help_text="Optional, shown alongside the number.")
    slug = models.SlugField(max_length=120, blank=True)

    class Meta:
        ordering = ["number"]
        unique_together = ("level", "number")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"Group {self.number}" + (f" — {self.title}" if self.title else "")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"group-{self.number}"
        super().save(*args, **kwargs)


class CardLesson(VideoContent, AudioContent):
    """One card's worth of content, scoped to its own (Group, Category)
    pair rather than shared across every category in the group — so
    the words, audio and video here belong only to this exact card
    (e.g. "Puzzle" for Group 5), never fetched from anywhere else.
    A group + category usually has several of these (several puzzle
    items, several vocabulary entries, ...), same as a word list."""

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=150, blank=True)
    word = models.TextField(
        blank=True, verbose_name="word or words",
        help_text="One word, or several sharing this card's audio — one per line "
                   "(numbering is optional, so \"1. seat\" and \"seat\" both work), "
                   "e.g.:\n1. seat\n2. feel\n3. sheep",
    )
    ipa = models.CharField(max_length=100, blank=True, help_text='Phonemic transcription, e.g. "/əˈtʃiːv/"')
    definition = models.TextField(
        blank=True, verbose_name="meaning or meanings",
        help_text="The meaning of each word above, in the same order — one per line "
                   "(numbering is optional), e.g.:\n1. a place to sit\n2. to touch gently\n3. a farm animal. "
                   "For Vocabulary cards, this is matched to the words by position.",
    )
    example_sentence = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="echospell/lessons/%Y/%m/", blank=True)
    body = models.TextField(blank=True, help_text="Optional teaching notes or instructions for this card.")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["group", "category", "order", "id"]

    def __str__(self):
        return ", ".join(self.word_list) or self.title or f"{self.category.name} — {self.group}"

    @property
    def word_list(self):
        """self.word parsed into individual words, in entry order — one
        per line, falling back to commas for a single-line entry, with
        any leading "1." / "1)" / "-" marker stripped from each."""
        raw = self.word.replace("\r\n", "\n")
        segments = raw.split("\n") if "\n" in raw else raw.split(",")
        return [cleaned for s in segments if (cleaned := _LIST_MARKER_RE.sub("", s).strip())]

    @property
    def definition_list(self):
        """self.definition parsed one meaning per line (never split on
        commas — unlike word_list, a meaning is prose and commas belong
        inside it), matched to word_list by position."""
        raw = self.definition.replace("\r\n", "\n")
        return [cleaned for line in raw.split("\n") if (cleaned := _LIST_MARKER_RE.sub("", line).strip())]

    @property
    def word_meaning_pairs(self):
        """(word, meaning) pairs by position — meaning is "" if fewer
        meanings were entered than words."""
        meanings = self.definition_list
        return [
            (w, meanings[i] if i < len(meanings) else "")
            for i, w in enumerate(self.word_list)
        ]


class Passage(AudioContent):
    """The group's reading passage — one per group."""

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="passage")
    title = models.CharField(max_length=150, blank=True)
    body = models.TextField(blank=True, help_text="Ideally built from this group's words.")

    def __str__(self):
        return self.title or f"Passage — {self.group}"


class Dialogue(AudioContent):
    """The group's conversational dialogue — one per group, made of DialogueLines."""

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="dialogue")
    title = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.title or f"Dialogue — {self.group}"


class DialogueLine(models.Model):
    dialogue = models.ForeignKey(Dialogue, on_delete=models.CASCADE, related_name="lines")
    speaker = models.CharField(max_length=20, default="A", help_text='e.g. "A" or "B"')
    text = models.TextField()
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.speaker}: {self.text[:40]}"


class Activity(VideoContent, AudioContent):
    """One scored exercise inside a group, e.g. "Transcribe these 8
    words".

    An activity belongs to exactly one Group — the level it sits in
    follows from that group, so the two can never disagree. Its `kind`
    (see activity_kinds.py) decides what learners see and how their
    answers are marked, so a new exercise type never needs a new model
    here.
    """

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="activities",
        help_text="The group this exercise belongs to.",
    )
    kind = models.CharField(
        max_length=40, choices=ACTIVITY_KIND_CHOICES, default="transcription",
        help_text="What learners do, and how their answers get marked.",
    )
    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, blank=True)
    instructions = models.TextField(
        blank=True, help_text="Shown above the questions. Leave blank to use this kind's standard wording.",
    )
    buckets = models.TextField(
        blank=True, verbose_name="sorting boxes",
        help_text="Only for Sound sort — the boxes to drag words into, one per line, e.g.:\n/iː/ as in sheep\n/ɪ/ as in ship",
    )
    pass_mark = models.PositiveIntegerField(
        default=70, help_text="Percentage needed to pass, e.g. 70",
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["group", "order", "id"]
        unique_together = ("group", "slug")
        verbose_name_plural = "Activities"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or self.kind
            slug = base
            i = 1
            while Activity.objects.filter(group=self.group, slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.kind_spec and self.kind_spec.mode == MODE_SORT and not self.bucket_list:
            raise ValidationError({"buckets": "A sound sort needs at least two boxes to drag into."})

    @property
    def level(self):
        return self.group.level

    @property
    def kind_spec(self):
        return get_kind(self.kind)

    @property
    def mode(self):
        return self.kind_spec.mode if self.kind_spec else ""

    @property
    def icon(self):
        return self.kind_spec.icon if self.kind_spec else "✏️"

    @property
    def kind_label(self):
        return self.kind_spec.label if self.kind_spec else self.kind

    @property
    def is_auto_marked(self):
        return bool(self.kind_spec and self.kind_spec.is_auto_marked)

    @property
    def display_instructions(self):
        return self.instructions or (self.kind_spec.instructions if self.kind_spec else "")

    @property
    def bucket_list(self):
        return _parse_lines(self.buckets)


class ActivityItem(AudioContent):
    """One question inside an activity."""

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="items")
    prompt = models.TextField(blank=True, help_text="What the learner is shown.")
    answer = models.TextField(
        blank=True,
        help_text="The correct answer. Separate equally correct answers with a vertical bar, e.g. colour|color",
    )
    options = models.TextField(
        blank=True, help_text="For multiple choice — the options, one per line.",
    )
    hint = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="echospell/activities/%Y/%m/", blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.prompt[:60] or self.first_answer[:60] or f"Item {self.order}"

    @property
    def option_list(self):
        return _parse_lines(self.options)

    @property
    def answer_alternatives(self):
        return [part.strip() for part in self.answer.split("|") if part.strip()]

    @property
    def first_answer(self):
        alts = self.answer_alternatives
        return alts[0] if alts else ""

    @property
    def token_list(self):
        """For Sentence builder — the answer's words, jumbled but stable
        for this item so a reload doesn't reshuffle the puzzle."""
        from .marking import shuffled_tokens

        if self.activity.kind == "listen-and-number":
            # Whole entries, one per line, so "ice cream" stays one piece.
            return shuffled_tokens(_parse_lines(self.first_answer), seed=self.pk or 0)
        return shuffled_tokens(self.first_answer, seed=self.pk or 0)


class ActivityAttempt(models.Model):
    """One learner's go at an activity, with its score."""

    STATUS_MARKED = "marked"
    STATUS_AWAITING = "awaiting"
    STATUS_REVIEWED = "reviewed"
    STATUS_CHOICES = [
        (STATUS_MARKED, "Marked automatically"),
        (STATUS_AWAITING, "Waiting for the teacher"),
        (STATUS_REVIEWED, "Reviewed by the teacher"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="echospell_attempts"
    )
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="attempts")
    score = models.PositiveIntegerField(default=0)
    max_score = models.PositiveIntegerField(default=0)
    percent = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_MARKED)
    teacher_feedback = models.TextField(blank=True)
    teacher_score = models.PositiveIntegerField(
        null=True, blank=True, help_text="Out of 100, for recorded activities.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.activity} ({self.percent}%)"

    def recalculate(self):
        """Score from the responses attached to this attempt."""
        responses = list(self.responses.all())
        marked = [r for r in responses if r.is_correct is not None]
        self.max_score = len(marked)
        self.score = sum(1 for r in marked if r.is_correct)
        self.percent = round(self.score * 100 / self.max_score) if self.max_score else 0
        self.status = self.STATUS_MARKED if marked else self.STATUS_AWAITING
        self.passed = bool(marked) and self.percent >= self.activity.pass_mark


class ActivityResponse(models.Model):
    """One answer within an attempt. `is_correct` is null while only a
    teacher can judge it — a recording, until it has been reviewed."""

    attempt = models.ForeignKey(ActivityAttempt, on_delete=models.CASCADE, related_name="responses")
    item = models.ForeignKey(ActivityItem, on_delete=models.CASCADE, related_name="responses")
    given = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    recording = models.FileField(upload_to="echospell/recordings/%Y/%m/", blank=True)

    class Meta:
        ordering = ["item__order", "id"]

    def __str__(self):
        return f"{self.item} → {self.given[:40] or 'recording'}"


class GroupProgress(models.Model):
    """One row per (user, group) they've marked complete."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="echospell_progress")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="progress_entries")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "group")
        verbose_name_plural = "Group progress"

    def __str__(self):
        return f"{self.user} — {self.group}"


class CardPosition(models.Model):
    """Where a learner last was in EchoSpell's cards — the card page and
    the exact card on it — so the dashboard can send them straight back.
    One row per learner, overwritten as they move."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="echospell_position")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="+")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="+")
    lesson = models.ForeignKey(CardLesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} — {self.group} · {self.category}"
