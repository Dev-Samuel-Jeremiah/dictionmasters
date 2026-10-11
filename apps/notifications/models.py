"""
A Notification is one saved update for one person: something that happened
(a test marked, a new pupil, a report card published). Reminders, the
things still to do, aren't saved: apps/notifications/reminders.py works them
out live, so they're always true and vanish once done.

`key` stops the same update being made twice (e.g. "assessment-open-12").
"""

from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        RESULT = "result", "Result"
        TEST = "test", "Test"
        REPORT = "report", "Report card"
        TO_MARK = "to_mark", "Work to mark"
        JOINED = "joined", "Someone joined"
        HELP = "help", "Help request"
        ASSIGNMENT = "assignment", "Assignment"
        NOTE = "note", "Note"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NOTE)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=300, blank=True, help_text="Where it leads: an address on this site.")
    key = models.CharField(max_length=120, blank=True, help_text="Stops the same update being made twice.")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "read_at"], name="notif_user_unread")]
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], condition=~models.Q(key=""), name="one_notification_per_key"),
        ]

    def __str__(self):
        return f"{self.user}: {self.title}"

    @property
    def is_unread(self):
        return self.read_at is None
