"""
The offline computer app (the separate "Diction Masters Desktop" project).

That app installs with every lesson already on the computer and works with
no internet at all. This small plug-in is all the website does for it:

    ActivationCode   what a school or learner types in once to unlock the
                     app: which levels it opens, on how many computers,
                     and until when.
    Activation       one computer that has used a code. Revoke it to free
                     the seat (the app is turned away when it next goes
                     online).
    ContentRelease   one snapshot of every lesson, built by
                     `manage.py export_desktop_content` (export.py). Installed
                     apps download only what changed since their own.

See DESKTOP_EDITION_GUIDE.md.
"""

import secrets

from django.db import models
from django.utils import timezone

from apps.echospell.models import LEVEL_NAME_CHOICES

# No 0/O, 1/I/L, 5/S, 2/Z: codes are read off paper and typed in by children.
CODE_ALPHABET = "ABCDEFGHJKMNPQRTUVWXY346789"


def new_code():
    groups = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "DM-" + "-".join(groups)


def clean_code(raw):
    """What someone typed, as the code is stored: capitals, dashes in place."""
    letters = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())
    if letters.startswith("DM"):
        letters = letters[2:]
    if len(letters) != 12:
        return ""
    return "DM-" + "-".join(letters[i:i + 4] for i in (0, 4, 8))


class ActivationCode(models.Model):
    code = models.CharField(max_length=20, unique=True, default=new_code, editable=False)
    holder = models.CharField(max_length=200, help_text="Who it is for: a school, a family, a learner.")
    levels = models.CharField(
        max_length=255, blank=True, default="",
        help_text='The levels it opens, stored as ",Level 1,Level 2,". Leave empty for every level.',
    )
    seats = models.PositiveIntegerField(default=1, help_text="How many computers may use this code.")
    valid_until = models.DateField(null=True, blank=True, help_text="Leave empty for no end date.")
    is_active = models.BooleanField(default=True, help_text="Untick to stop the code (and every computer using it).")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ({self.holder})"

    @property
    def level_list(self):
        """The levels it opens, or [] for every level."""
        return [part for part in self.levels.split(",") if part]

    def set_levels(self, names):
        names = [name for name in names if name]
        self.levels = f",{','.join(names)}," if names else ""

    def levels_label(self):
        return ", ".join(self.level_list) or "Every level"
    levels_label.short_description = "Levels"

    def expired(self, today=None):
        return bool(self.valid_until and (today or timezone.localdate()) > self.valid_until)

    def seats_used(self):
        return self.activations.filter(revoked=False).count()
    seats_used.short_description = "Computers"

    def opens(self):
        """The level names it opens: every level when none are ticked."""
        return self.level_list or [value for value, _label in LEVEL_NAME_CHOICES]


class Activation(models.Model):
    code = models.ForeignKey(ActivationCode, on_delete=models.CASCADE, related_name="activations")
    device_id = models.CharField(max_length=80)
    device_name = models.CharField(max_length=200, blank=True)
    learner_name = models.CharField(max_length=200, blank=True)
    system = models.CharField(max_length=40, blank=True, help_text="windows, linux or mac")
    app_version = models.CharField(max_length=40, blank=True)
    content_release = models.PositiveIntegerField(default=0, help_text="The lessons it had at its last check-in.")
    activated_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(default=timezone.now)
    revoked = models.BooleanField(default=False, help_text="Tick to free this seat; the app locks when it next goes online.")

    class Meta:
        ordering = ["-last_seen"]
        unique_together = ("code", "device_id")

    def __str__(self):
        return f"{self.device_name or self.device_id} on {self.code.code}"


class ContentRelease(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting to start"
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    levels = models.CharField(max_length=255, blank=True, default="", help_text="Empty: every level.")
    include_videos = models.BooleanField(default=True)
    manifest = models.CharField(max_length=255, blank=True, help_text="Where its list is kept in storage.")
    pages = models.PositiveIntegerField(default=0)
    files = models.PositiveIntegerField(default=0)
    size = models.BigIntegerField(default=0, help_text="Everything in it, in bytes.")
    new_size = models.BigIntegerField(default=0, help_text="What changed since the last release, in bytes.")
    skipped = models.TextField(blank=True, help_text="Pages that couldn't be kept, and why.")
    error = models.TextField(blank=True)
    progress = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pk"]

    def __str__(self):
        return f"Lessons release {self.pk} ({self.get_status_display()})"

    @classmethod
    def latest(cls):
        return cls.objects.filter(status=cls.Status.READY).order_by("-pk").first()


class ComputerUnlock(models.Model):
    """One computer unlocked with no internet (unlock.py): the number the
    computer showed, the level, the end date, and the code made for it.
    "Revoked" only reaches the computer if it ever goes online; the end date
    always applies, online or not."""

    computer = models.CharField(max_length=8, help_text="The number the computer shows, e.g. K7QX-3MPA.")
    level = models.CharField(max_length=40, choices=LEVEL_NAME_CHOICES)
    valid_until = models.DateField(null=True, blank=True, help_text="Leave empty for no end date.")
    holder = models.CharField(max_length=200, help_text="Who it is for: the school, family or learner.")
    notes = models.TextField(blank=True, help_text="Anything to remember: the room, the person who asked, how they paid.")
    code = models.CharField(max_length=40, editable=False)
    revoked = models.BooleanField(default=False, help_text="Stops it only when that computer next goes online.")
    created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True, help_text="The last time it went online, if ever.")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Unlocked computer"

    def __str__(self):
        return f"{self.computer_label} · {self.level} · {self.holder}"

    @property
    def computer_label(self):
        return f"{self.computer[:4]}-{self.computer[4:]}"


class DesktopBundle(models.Model):
    """One level's zip for flash drives (bundles.py): its installers for every
    kind of computer, built on GitHub, and its videos, from storage."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting to start"
        BUILDING = "building", "Packing"
        READY = "ready", "Ready to download"
        FAILED = "failed", "Failed"

    level = models.CharField(max_length=40, choices=LEVEL_NAME_CHOICES)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    file = models.CharField(max_length=255, blank=True, help_text="Where the zip is kept in storage.")
    size = models.BigIntegerField(default=0)
    videos = models.PositiveIntegerField(default=0)
    progress = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pk"]
        verbose_name = "Offline app download"

    def __str__(self):
        return f"{self.level} ({self.get_status_display()})"
