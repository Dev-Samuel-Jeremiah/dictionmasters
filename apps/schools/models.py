"""
A School is the account a school admin registers. It can't create or
upload any content — it only ever looks at content someone else
published, and manages who from its school is allowed in.

Access into a school is entirely code-based: a school admin generates
an AccessCode for a teacher or a student, hands it over, and that one
code is redeemed exactly once, on the "join with a code" page, to
create that person's account already linked to the right school.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from .utils import generate_access_code, generate_school_code


class School(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=16, unique=True, editable=False)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_school_code(School)
        super().save(*args, **kwargs)

    @property
    def teachers(self):
        return self.members.filter(role="teacher")

    @property
    def students(self):
        return self.members.filter(role="student")


class AccessCode(models.Model):
    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="access_codes")
    role = models.CharField(max_length=20, choices=Role.choices)

    # The level this code puts them in. Whoever redeems it studies or
    # teaches that level, and sees only that level's work.
    level = models.CharField(max_length=100, blank=True)
    code = models.CharField(max_length=10, unique=True, editable=False)

    # A free-text note for the admin's own reference, e.g. "Primary 5
    # — Mrs Okafor's class". Never shown to anyone outside the school.
    label = models.CharField(max_length=100, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="issued_codes",
    )
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="joined_via_code",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ({self.get_role_display()}, {self.school})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_access_code(AccessCode)
        super().save(*args, **kwargs)

    @property
    def is_used(self):
        return self.used_by_id is not None

    def mark_used_by(self, user):
        self.used_by = user
        self.used_at = timezone.now()
        self.save(update_fields=["used_by", "used_at"])
