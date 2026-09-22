from django.conf import settings
from django.db import models


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
