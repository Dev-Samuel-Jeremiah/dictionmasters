"""
Diction Clash — a word game built from the Quick Words library.

A Match is one game: a mode, a difficulty and a running score. Each
question in it is a Round, generated on demand from a Quick Word. The
round stores exactly what the player was shown and the correct answer,
so the review afterwards shows the question as it was asked — even if
the word is later edited.

Everything that decides a result happens on the server: when the round
was shown, when it was answered, whether the clock had already run out.
"""

from django.conf import settings
from django.db import models

from apps.quick_words.models import QuickWord

from .catalogue import MODES, TIERS, TYPE_LABELS, TYPED_TYPES


class Match(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "In play"
        FINISHED = "finished", "Finished"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clash_matches")
    mode = models.CharField(max_length=20, choices=[(m.slug, m.label) for m in MODES.values()])
    difficulty = models.CharField(max_length=20, choices=[(t.slug, t.label) for t in TIERS.values()])
    seed = models.BigIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    score = models.IntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    wrong = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    best_streak = models.PositiveIntegerField(default=0)
    lives = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name_plural = "Matches"

    def __str__(self):
        return f"{self.user} — {self.mode_spec.label} ({self.tier.label})"

    @property
    def mode_spec(self):
        return MODES[self.mode]

    @property
    def tier(self):
        return TIERS[self.difficulty]

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def answered(self):
        return self.correct + self.wrong

    @property
    def accuracy(self):
        return round(self.correct * 100 / self.answered) if self.answered else 0


class Round(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=30)
    word = models.ForeignKey(QuickWord, on_delete=models.SET_NULL, null=True, related_name="+")

    # What the player saw, frozen at the moment of asking.
    prompt = models.TextField(blank=True)
    prompt_detail = models.CharField(max_length=255, blank=True)
    options = models.JSONField(default=list, blank=True)
    answer = models.CharField(max_length=255)
    seconds = models.PositiveIntegerField(default=0)

    shown_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    given = models.CharField(max_length=255, blank=True)
    is_correct = models.BooleanField(null=True)
    timed_out = models.BooleanField(default=False)
    points = models.IntegerField(default=0)

    class Meta:
        ordering = ["number"]
        unique_together = ("match", "number")

    def __str__(self):
        return f"{self.match} — round {self.number}"

    @property
    def label(self):
        return TYPE_LABELS.get(self.kind, "")

    @property
    def is_typed(self):
        return self.kind in TYPED_TYPES

    @property
    def is_pending(self):
        return self.is_correct is None

    @property
    def response_seconds(self):
        if not self.answered_at:
            return None
        return round((self.answered_at - self.shown_at).total_seconds(), 1)
