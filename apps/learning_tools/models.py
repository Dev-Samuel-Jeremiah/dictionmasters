"""
Scan & Listen readings: the text of a scanned (or typed) page and its
read-aloud, kept so they can be found and played again instead of being
made again (apps/learning_tools/scan_library.py).

A reading made by someone in a school belongs to that school: everyone
there can search for it and listen. An individual learner's readings are
their own. The audio is played through the protected player and can only
be kept for offline listening inside the app (apps/videos) — never handed
over as a file.
"""

from django.conf import settings
from django.db import models
from django.urls import reverse


class ScanReading(models.Model):
    STATUS_CHOICES = [("", "No audio"), ("working", "Making audio"), ("ready", "Audio ready"), ("failed", "Failed")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                              related_name="scan_readings")
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, null=True, blank=True,
                               related_name="scan_readings")
    title = models.CharField(max_length=200)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # The read-aloud. audio_text is exactly what the voice read; audio_hash
    # identifies that recording (voice + words), so the same words are
    # never paid for twice — another reading with the same hash shares it.
    audio_file = models.FileField(upload_to="scan_listen/%Y/%m/", blank=True)
    audio_text = models.TextField(blank=True)
    audio_hash = models.CharField(max_length=64, blank=True, db_index=True)
    audio_duration = models.FloatField(null=True, blank=True)
    audio_status = models.CharField(max_length=10, choices=STATUS_CHOICES, blank=True, default="")
    audio_error = models.CharField(max_length=300, blank=True)
    audio_updated = models.DateTimeField(null=True, blank=True)
    plays = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("learning_tools:book_scanner") + f"?reading={self.pk}"

    @property
    def has_audio(self):
        return self.audio_status == "ready" and bool(self.audio_file)

    @property
    def audio_blocks(self):
        return [p for p in self.audio_text.split("\n\n") if p.strip()]

    @property
    def words(self):
        return len(self.text.split())

    # read_along looks for an audio_url beside audio_file.
    @property
    def audio_url(self):
        return ""

    def read_along_self_timed(self):
        """Its timings come with the voice: never measured over."""
        return True

    # The offline player (apps/videos) plays and keeps any row with a
    # video_file; here that's the read-aloud.
    @property
    def video_file(self):
        return self.audio_file if self.has_audio else None

    @property
    def video_source(self):
        return "audio" if self.has_audio else ""

    @property
    def video_caption(self):
        return f"Scan & Listen: {self.title}"
