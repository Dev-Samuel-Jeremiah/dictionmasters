"""
Conversational Dialogue: short everyday conversations to say aloud, one
for each school day.

Level (Pre-Level, Level 1, ...) > Term 1-3 > Week 1-10 > Monday-Friday >
Dialogue. A Dialogue has target words ("lion, gorilla, tortoise") and a
script of speakers and lines, with a recording to follow:

    Child: Mummy, is that a lion?
    Mummy: No, that's a gorilla.

Terms, weeks and days are simply chosen on the dialogue itself, so a new
dialogue is one form: pick the level, term, week and day, then write it.
"""

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.book.models import AudioContent, VideoContent
from apps.echospell.models import LEVEL_NAME_CHOICES

LEVEL_ORDER = [value for value, _label in LEVEL_NAME_CHOICES]
TERM_CHOICES = [(n, f"Term {n}") for n in (1, 2, 3)]
WEEK_CHOICES = [(n, f"Week {n}") for n in range(1, 11)]
DAY_CHOICES = [
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
]
DAY_ORDER = [key for key, _label in DAY_CHOICES]


class DialogueLevel(models.Model):
    name = models.CharField(max_length=100, choices=LEVEL_NAME_CHOICES, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True, help_text="One line shown on the level's card.")
    order = models.PositiveIntegerField(default=0, editable=False)
    is_published = models.BooleanField(default=True, help_text="Unpublished levels are hidden from learners.")

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "level"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.order = LEVEL_ORDER.index(self.name) if self.name in LEVEL_ORDER else len(LEVEL_ORDER)
        if not self.slug:
            self.slug = slugify(self.name) or "level"
        super().save(*args, **kwargs)


class Dialogue(VideoContent, AudioContent):
    level = models.ForeignKey(DialogueLevel, on_delete=models.CASCADE, related_name="dialogues")
    term = models.PositiveSmallIntegerField(choices=TERM_CHOICES, default=1)
    week = models.PositiveSmallIntegerField(choices=WEEK_CHOICES, default=1)
    day = models.CharField(max_length=10, choices=DAY_CHOICES, default="monday")
    day_order = models.PositiveSmallIntegerField(default=0, editable=False)
    title = models.CharField(max_length=150, help_text='The topic, e.g. "Animals"')
    slug = models.SlugField(max_length=170, blank=True)
    target_words = models.TextField(
        blank=True, help_text="The words this dialogue practises, separated by commas: lion, gorilla, tortoise, giraffe",
    )
    script = models.TextField(
        blank=True,
        help_text="One line each, as Speaker: words. For example:\n"
                  "Child: Mummy, is that a lion?\nMummy: No, that's a gorilla.",
    )
    notes = models.TextField(blank=True, help_text="Optional tips for the teacher, e.g. how to act it out.")
    order = models.PositiveIntegerField(default=0, help_text="For more than one dialogue on the same day.")
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["level__order", "term", "week", "day_order", "order", "id"]
        unique_together = ("level", "slug")

    def __str__(self):
        return f"{self.level.name} · Term {self.term} · Week {self.week} · {self.get_day_display()} — {self.title}"

    def save(self, *args, **kwargs):
        self.day_order = DAY_ORDER.index(self.day) if self.day in DAY_ORDER else 0
        if not self.slug:
            base = slugify(f"t{self.term}-w{self.week}-{self.day}-{self.title}") or "dialogue"
            slug, i = base, 1
            while Dialogue.objects.filter(level_id=self.level_id, slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def words(self):
        raw = (self.target_words or "").replace("\n", ",")
        return [w.strip() for w in raw.split(",") if w.strip()]

    @property
    def lines(self):
        """[(speaker, words), ...] from the script. A line without a
        "Speaker:" carries on with the last speaker."""
        out, speaker = [], ""
        for raw in (self.script or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            head, sep, rest = line.partition(":")
            if sep and head.strip() and len(head.strip()) <= 30 and rest.strip():
                speaker, line = head.strip(), rest.strip()
            out.append((speaker, line))
        return out

    @property
    def speakers(self):
        seen = []
        for speaker, _line in self.lines:
            if speaker and speaker not in seen:
                seen.append(speaker)
        return seen

    @property
    def place(self):
        return f"Term {self.term} · Week {self.week} · {self.get_day_display()}"


class DialogueProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dialogue_progress")
    dialogue = models.ForeignKey(Dialogue, on_delete=models.CASCADE, related_name="progress_entries")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "dialogue")
        verbose_name_plural = "dialogue progress"

    def __str__(self):
        return f"{self.user} — {self.dialogue}"
