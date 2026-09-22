from django.conf import settings
from django.db import models

from apps.book.models import AudioContent, VideoContent
from apps.echospell.models import ActivityAttemptBase, ActivityBase, ActivityItemBase


class TrickProgress(models.Model):
    """Which tabs of a trick a learner has opened. A trick is finished once
    every tab with something in it has been opened; only then can its
    assessment be taken (apps/tricks/progress.py)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trick_progress")
    trick = models.ForeignKey("book.Sound", on_delete=models.CASCADE, related_name="progress")
    tabs_seen = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "trick"], name="one_progress_per_trick")]
        verbose_name = "trick progress"
        verbose_name_plural = "trick progress"

    def __str__(self):
        return f"{self.user} — {self.trick}"


# ---------------------------------------------------------------------------
# A trick's assessment: activities of any EchoSpell type (activity_kinds.py)
# — transcription, sound sort, minimal pairs, read aloud and the rest —
# marked the same way. Passing them all unlocks the next trick.
# ---------------------------------------------------------------------------

class TrickActivity(VideoContent, AudioContent, ActivityBase):
    trick = models.ForeignKey(
        "book.Sound", on_delete=models.CASCADE, related_name="trick_activities",
        limit_choices_to={"category__programme": "tricks"},
        help_text="The trick this activity tests. Passing all of a trick's activities unlocks the next trick.",
    )

    class Meta:
        ordering = ["trick", "order", "id"]
        unique_together = ("trick", "slug")
        verbose_name = "trick activity"
        verbose_name_plural = "trick activities"

    def save(self, *args, **kwargs):
        self._unique_slug(trick=self.trick)
        super().save(*args, **kwargs)


class TrickActivityItem(AudioContent, ActivityItemBase):
    activity = models.ForeignKey(TrickActivity, on_delete=models.CASCADE, related_name="items")
    image = models.ImageField(upload_to="tricks/activities/%Y/%m/", blank=True)

    class Meta(ActivityItemBase.Meta):
        verbose_name = "activity question"


class TrickActivityAttempt(ActivityAttemptBase):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trick_activity_attempts")
    activity = models.ForeignKey(TrickActivity, on_delete=models.CASCADE, related_name="attempts")

    class Meta(ActivityAttemptBase.Meta):
        verbose_name = "trick activity attempt"


class TrickActivityResponse(models.Model):
    """One answer within an attempt. `is_correct` stays empty for a
    recording, which a teacher listens to."""

    attempt = models.ForeignKey(TrickActivityAttempt, on_delete=models.CASCADE, related_name="responses")
    item = models.ForeignKey(TrickActivityItem, on_delete=models.CASCADE, related_name="responses")
    given = models.TextField(blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    recording = models.FileField(upload_to="tricks/recordings/%Y/%m/", blank=True)

    class Meta:
        ordering = ["item__order", "id"]
