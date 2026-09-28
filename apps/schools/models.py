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
    # Set in the control room. Blank means no limit.
    max_teachers = models.PositiveIntegerField(
        "Teachers allowed", null=True, blank=True,
        help_text="How many teachers this school may register. Leave blank for no limit.",
    )
    max_students = models.PositiveIntegerField(
        "Students allowed", null=True, blank=True,
        help_text="How many students this school may register. Leave blank for no limit.",
    )
    # A trial set for this school in the control room (Billing settings),
    # instead of the general trial length. Blank = the general trial.
    TRIAL_UNITS = [("days", "days"), ("weeks", "weeks"), ("months", "months")]
    trial_length = models.PositiveIntegerField(null=True, blank=True)
    trial_unit = models.CharField(max_length=10, choices=TRIAL_UNITS, default="days")
    trial_set_at = models.DateTimeField(null=True, blank=True)
    trial_reason = models.CharField(max_length=120, blank=True, help_text="Shown to the school beside its trial days.")
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

    def paid_plan(self):
        """The school plan being paid for right now, or None."""
        from django.utils import timezone

        subscription = getattr(self, "subscription", None) if self.pk else None
        if subscription and subscription.plan and subscription.paid_until and subscription.paid_until > timezone.now():
            return subscription.plan
        return None

    def chosen_plan(self):
        """The school plan that sets its size: the one it's paying for, or
        the one it picked when it registered and is trying for free."""
        subscription = getattr(self, "subscription", None) if self.pk else None
        return subscription.plan if subscription and subscription.plan_id else None

    @property
    def plan_teacher_limit(self):
        """The teachers its plan allows. A school with no plan at all gets
        the smallest school plan's allowance, so no school is uncapped."""
        from apps.billing.models import Plan

        plan = self.chosen_plan()
        if plan and plan.max_units:
            return plan.max_units
        if self.max_teachers is not None:
            return None
        entry = (
            Plan.objects.filter(is_active=True, audience=Plan.AUDIENCE_SCHOOL, max_units__isnull=False)
            .order_by("max_units").first()
        )
        return entry.max_units if entry else None

    @property
    def teacher_limit(self):
        """The teachers this school may register: its plan's allowance, or
        the number set in the control room if that's lower. None only when
        there are no school plans at all."""
        limits = [n for n in (self.max_teachers, self.plan_teacher_limit) if n is not None]
        return min(limits) if limits else None

    @property
    def teacher_places_left(self):
        limit = self.teacher_limit
        return None if limit is None else max(0, limit - self.teachers.count())

    @property
    def teachers_full(self):
        limit = self.teacher_limit
        return limit is not None and self.teachers.count() >= limit

    def current_plan(self):
        from django.utils import timezone

        plan = self.paid_plan()
        if plan is None:
            return "—"
        band = f" · {plan.band_label}" if plan.band_label else ""
        return f"{plan.name}{band} (until {timezone.localtime(self.subscription.paid_until):%d %b %Y})"
    current_plan.short_description = "Current plan"

    @property
    def custom_trial_label(self):
        if not self.trial_length:
            return ""
        unit = self.trial_unit if self.trial_length != 1 else self.trial_unit.rstrip("s")
        return f"{self.trial_length} {unit}"

    def trial_end_from(self, start):
        """When a trial of this school's own length, begun at `start`, ends."""
        from apps.billing.access import add_trial

        return add_trial(start, self.trial_length or 0, self.trial_unit)

    @property
    def students_full(self):
        return self.max_students is not None and self.students.count() >= self.max_students


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
