"""
Who may keep a lesson video on their own device, and for how long.

Videos are never handed to the browser as a plain address: they are
streamed through Django from private R2 storage, on a signed link that
belongs to one signed-in person and lasts minutes (see links.py).

A learner may also keep a copy for watching without the internet. The
copy is stored by the browser, encrypted with a key the browser makes
and will not hand back (static/js/offline_video.js), so a copied store
is of no use on another device or in another browser. Django decides who
may keep a copy, on how many devices, and until when — and can take a
copy back by revoking it, which is noticed the next time that device is
online.

Being straight about the limit: this is not DRM. It keeps lessons off
the open web and out of casual sharing; it cannot stop someone
determined from recording what their own screen plays.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


def license_days():
    return int(getattr(settings, "OFFLINE_VIDEO_LICENSE_DAYS", 7))


def device_limit():
    return int(getattr(settings, "MAX_OFFLINE_DEVICES_PER_STUDENT", 2))


class StudentDevice(models.Model):
    """One phone, tablet or computer a learner keeps lesson copies on."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    device_identifier = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True, help_text="What the learner calls it, or what the browser says.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Turn off to stop new copies and end the ones it holds.")

    class Meta:
        ordering = ["-last_seen_at"]
        verbose_name = "learner device"

    def __str__(self):
        return f"{self.name or 'Device'} — {self.student}"

    @property
    def copies_held(self):
        return self.licenses.filter(is_active=True, revoked_at__isnull=True).count()


class OfflineVideoLicense(models.Model):
    """Permission for one device to keep one video until a date."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offline_licenses")
    device = models.ForeignKey(StudentDevice, on_delete=models.CASCADE, related_name="licenses")
    # The video itself lives on whichever lesson model holds it, so the
    # licence points at that row rather than a table of its own.
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    video = GenericForeignKey("content_type", "object_id")
    title = models.CharField(max_length=200, blank=True, help_text="What the learner sees in their offline list.")

    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["device", "content_type", "object_id"], name="one_copy_per_device"),
        ]
        verbose_name = "offline copy"
        verbose_name_plural = "offline copies"

    def __str__(self):
        return f"{self.title or 'Video'} on {self.device}"

    @property
    def is_live(self):
        return (self.is_active and self.revoked_at is None and self.device.is_active
                and self.expires_at > timezone.now())

    @property
    def days_left(self):
        return max((self.expires_at - timezone.now()).days, 0)

    @classmethod
    def new_expiry(cls):
        return timezone.now() + timedelta(days=license_days())

    def renew(self):
        self.expires_at = self.new_expiry()
        self.revoked_at = None
        self.is_active = True
        self.save(update_fields=["expires_at", "revoked_at", "is_active"])
        return self
