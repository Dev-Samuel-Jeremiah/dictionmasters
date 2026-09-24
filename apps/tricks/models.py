"""
Lesson assessments and progress, for both programmes built on the lesson
pages: 44 Academy's sounds and Tricks to Sound Fluent's tricks.

Each lesson (a book.Sound, whichever programme it is in) can have
assessment activities of any EchoSpell type (activity_kinds.py) —
transcription, sound sort, minimal pairs, read aloud and the rest —
marked the same way. A programme's lessons are taken in order: finishing
one and passing its activities unlocks the next (apps/tricks/progress.py).
"""

from django.conf import settings
from django.db import models

from apps.book.models import AudioContent, VideoContent
from apps.echospell.models import ActivityAttemptBase, ActivityBase, ActivityItemBase, RECORDING_MARK_CHOICES


class LessonProgress(models.Model):
    """Which tabs of a lesson a learner has opened. A lesson is finished
    once every tab with something in it has been opened; only then can its
    assessment be taken."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey("book.Sound", on_delete=models.CASCADE, related_name="progress")
    tabs_seen = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "lesson"], name="one_progress_per_lesson")]
        verbose_name = "lesson progress"
        verbose_name_plural = "lesson progress"

    def __str__(self):
        return f"{self.user} — {self.lesson}"


class LessonActivity(VideoContent, AudioContent, ActivityBase):
    lesson = models.ForeignKey(
        "book.Sound", on_delete=models.CASCADE, related_name="lesson_activities",
        help_text="The sound or trick this activity tests. Passing all of a lesson's activities unlocks the next one.",
    )

    class Meta:
        ordering = ["lesson", "order", "id"]
        unique_together = ("lesson", "slug")
        verbose_name = "assessment activity"
        verbose_name_plural = "assessment activities"

    def save(self, *args, **kwargs):
        self._unique_slug(lesson=self.lesson)
        super().save(*args, **kwargs)


class LessonActivityItem(AudioContent, ActivityItemBase):
    activity = models.ForeignKey(LessonActivity, on_delete=models.CASCADE, related_name="items")
    image = models.ImageField(upload_to="tricks/activities/%Y/%m/", blank=True)

    class Meta(ActivityItemBase.Meta):
        verbose_name = "activity question"


class LessonActivityAttempt(ActivityAttemptBase):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_activity_attempts")
    activity = models.ForeignKey(LessonActivity, on_delete=models.CASCADE, related_name="attempts")

    class Meta(ActivityAttemptBase.Meta):
        verbose_name = "assessment activity attempt"


class LessonActivityResponse(models.Model):
    """One answer within an attempt. `is_correct` stays empty for a
    recording until a teacher has listened to it."""

    attempt = models.ForeignKey(LessonActivityAttempt, on_delete=models.CASCADE, related_name="responses")
    item = models.ForeignKey(LessonActivityItem, on_delete=models.CASCADE, related_name="responses")
    given = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    awarded_mark = models.PositiveSmallIntegerField(
        choices=RECORDING_MARK_CHOICES, null=True, blank=True,
        help_text="Teacher-awarded mark for a recording, from 0 to 5.",
    )
    recording = models.FileField(upload_to="tricks/recordings/%Y/%m/", blank=True)

    class Meta:
        ordering = ["item__order", "id"]
