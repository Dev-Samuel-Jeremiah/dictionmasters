"""
Lesson packs: one level's pictures, recordings and videos in a single
encrypted file, to copy to a flash drive and load into the apps without
downloading gigabytes on every device (apps/offline/packs.py builds them).
"""

from django.conf import settings
from django.db import models

from apps.echospell.models import LEVEL_NAME_CHOICES


class LessonPack(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting to start"
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    level = models.CharField(max_length=20, choices=LEVEL_NAME_CHOICES)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    file = models.FileField(upload_to="offline-packs/", blank=True)
    # The pack's own key (32 random bytes, base64). Given only to a signed-in
    # learner of this level with a plan running, so a copied flash drive is of
    # no use on its own.
    key = models.CharField(max_length=64, editable=False)
    size = models.BigIntegerField(default=0)
    files_total = models.PositiveIntegerField(default=0)
    files_done = models.PositiveIntegerField(default=0)
    videos = models.PositiveIntegerField(default=0)
    missing = models.PositiveIntegerField(default=0, help_text="Files listed but not found in storage.")
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.level} lesson pack ({self.get_status_display()})"

    @property
    def filename(self):
        return f"Diction Masters {self.level} lessons.dmpack"
