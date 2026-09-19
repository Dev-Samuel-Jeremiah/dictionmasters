"""
The live AI reading tutor.

A learner picks a passage and reads it aloud, a sentence at a time. The
tutor listens to each sentence; when a word goes wrong it stops, says the
word properly, and has the learner say it back before carrying on. At the
end it works out a reading level and gives feedback.

    TutorPassage   what there is to read, by level
    TutorSession   one reading of one passage: every sentence's verdict,
                   the scores, the reading level and the feedback
    TutorSpeech    a word or sentence spoken by the tutor's voice, made
                   once and kept, so the same word is never paid for twice
"""

import hashlib

from django.conf import settings
from django.db import models

from apps.echospell.models import LEVEL_NAME_CHOICES

LEVEL_ORDER = [value for value, _label in LEVEL_NAME_CHOICES]


def level_index(name):
    try:
        return LEVEL_ORDER.index(name)
    except ValueError:
        return 0


class TutorPassage(models.Model):
    title = models.CharField(max_length=150)
    level = models.CharField(
        max_length=100, choices=LEVEL_NAME_CHOICES, default="Level 1",
        help_text="The level this passage is written for. The tutor measures reading level against it.",
    )
    body = models.TextField(
        help_text="The passage. Keep it to what a learner can read in two or three minutes; "
                  "blank lines separate paragraphs.",
    )
    summary = models.CharField(max_length=200, blank=True, help_text="One line shown on the passage card.")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "tutor passage"

    def __str__(self):
        return f"{self.title} ({self.level})"

    @property
    def level_rank(self):
        return level_index(self.level)

    @property
    def word_count(self):
        return len(self.body.split())


class TutorSession(models.Model):
    STATUS_READING = "reading"
    STATUS_DONE = "done"
    STATUS_CHOICES = [(STATUS_READING, "Reading"), (STATUS_DONE, "Finished")]

    BAND_INDEPENDENT = "independent"
    BAND_INSTRUCTIONAL = "instructional"
    BAND_FRUSTRATION = "frustration"
    BAND_CHOICES = [
        (BAND_INDEPENDENT, "Reads it comfortably"),
        (BAND_INSTRUCTIONAL, "Right level to learn from"),
        (BAND_FRUSTRATION, "Too hard for now"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tutor_sessions")
    passage = models.ForeignKey(TutorPassage, on_delete=models.SET_NULL, null=True, related_name="sessions")
    # The passage as read, kept so a report still makes sense if the
    # passage is later edited or removed.
    title = models.CharField(max_length=150)
    passage_level = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_READING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # {"0": {"words": [...], "right": 7, "total": 8, "seconds": 3.1, "tries": 1}, ...}
    # The first reading of each sentence is what's scored.
    sentences = models.JSONField(default=dict, blank=True)
    # {"think": {"tries": 2, "ok": true}, ...} — words practised with the tutor.
    practised = models.JSONField(default=dict, blank=True)
    checks = models.PositiveIntegerField(default=0)
    sentences_read = models.PositiveIntegerField(default=0)
    sentences_total = models.PositiveIntegerField(default=0)

    words_total = models.PositiveIntegerField(default=0)
    words_correct = models.PositiveIntegerField(default=0)
    accuracy = models.FloatField(null=True, blank=True)
    wcpm = models.FloatField(null=True, blank=True, verbose_name="words correct per minute")
    reading_seconds = models.FloatField(null=True, blank=True)
    band = models.CharField(max_length=15, choices=BAND_CHOICES, blank=True)
    reading_level = models.CharField(max_length=100, blank=True)
    # [{"word": "three", "heard": "tree", "tips": [...]}, ...]
    mistakes = models.JSONField(default=list, blank=True)
    # [{"label": "/θ/ (as in ‘think’) said as /t/", "count": 3, "words": [...]}, ...]
    patterns = models.JSONField(default=list, blank=True)
    # {"headline": "...", "message": "...", "tips": [...], "source": "ai"|"rules"}
    feedback = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "tutor session"

    def __str__(self):
        return f"{self.user} — {self.title} ({self.started_at:%d %b %Y})"

    @property
    def accuracy_percent(self):
        return round(self.accuracy * 100) if self.accuracy is not None else None


class TutorSpeech(models.Model):
    key = models.CharField(max_length=64, unique=True)
    text = models.CharField(max_length=600)
    audio = models.FileField(upload_to="tutor/speech/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tutor speech"
        verbose_name_plural = "tutor speech"

    def __str__(self):
        return self.text[:80]

    @staticmethod
    def key_for(text):
        return hashlib.sha256(" ".join(str(text).split()).lower().encode("utf-8")).hexdigest()
