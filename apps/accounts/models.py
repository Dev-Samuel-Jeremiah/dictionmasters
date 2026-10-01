"""
A single custom User model carries everyone on Diction Masters —
a school admin, a teacher, a student, or an individual learner who
signed up on their own. `role` decides what they can do; `school`
decides what they can see.

Email is the account's unique identifier. Accounts with a username can
also sign in with it, which is useful for school admins and students who
receive generated credentials.
"""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.hashers import is_password_usable
from django.core.validators import FileExtensionValidator
from django.db import models


INTERNAL_EMAIL_DOMAIN = "students.dictionmasters.app"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.INDIVIDUAL)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.INDIVIDUAL)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("first_name", "Admin")
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        SCHOOL_ADMIN = "school_admin", "School admin"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        INDIVIDUAL = "individual", "Individual learner"

    email = models.EmailField(unique=True)
    # Students can sign in with a username instead of an email (bulk-added
    # students, or any student who signs up without one). An account with no
    # email of its own keeps an internal one, ending in INTERNAL_EMAIL_DOMAIN,
    # that is never shown or used for mail.
    username = models.CharField(
        max_length=40, unique=True, null=True, blank=True,
        help_text="Optional. Students can sign in with this instead of an email: letters, numbers, dots and dashes.",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices)

    # The level this person studies or teaches, e.g. "Level 3". Set from
    # the joining code their school gave them, and it decides what they
    # can open: a Level 3 student sees Level 3 and nothing else.
    # Left blank for individual learners and school admins, who see
    # every level.
    level = models.CharField(max_length=100, blank=True)
    # A teacher who covers more than one level (a teacher who takes Level
    # 1, Level 3 and Level 6, say) has the rest here, beyond the main one
    # above — `level` stays whichever one page and joining code always
    # show a single value for. Stored as ",Level 3,Level 6," (with the
    # commas either side) so "Level 1" can never match inside "Level 12".
    # Set from the control room (apps/manage/level_field.py); see
    # `all_levels` below and apps/accounts/access.py, which gates on all
    # of them together.
    additional_levels = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Other levels they also teach or study, besides the main one above.",
    )

    # Set for school_admin, teacher and student. Left blank for an
    # individual learner who registered on their own.
    school = models.ForeignKey(
        "schools.School",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="members",
    )

    # Passwords remain Django-hashed for authentication. This separate field
    # keeps an encrypted copy only so school staff can re-download login
    # details for accounts created or updated after credential recovery was
    # enabled. It is never exposed in a form or admin fieldset.
    encrypted_login_password = models.TextField(blank=True, default="", editable=False)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Grants access to the Django admin. Platform staff only.",
    )
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    def set_password(self, raw_password):
        super().set_password(raw_password)
        if (
            raw_password is not None
            and self.school_id
            and self.role in {self.Role.SCHOOL_ADMIN, self.Role.TEACHER, self.Role.STUDENT}
            and is_password_usable(self.password)
        ):
            from .credentials import encrypt_login_password

            self.encrypted_login_password = encrypt_login_password(raw_password)
        else:
            self.encrypted_login_password = ""

    def set_unusable_password(self):
        super().set_unusable_password()
        self.encrypted_login_password = ""

    def check_password(self, raw_password):
        """Keep the entered password encrypted after a valid school login.

        This lets existing accounts become downloadable over time without
        changing their password. The normal authentication hash remains the
        source of truth for sign-in.
        """
        saved_ciphertext = self.encrypted_login_password
        valid = super().check_password(raw_password)
        if (
            valid
            and raw_password is not None
            and self.school_id
            and self.role in {self.Role.SCHOOL_ADMIN, self.Role.TEACHER, self.Role.STUDENT}
        ):
            from .credentials import decrypt_login_password, encrypt_login_password

            if decrypt_login_password(saved_ciphertext) != raw_password:
                encrypted = encrypt_login_password(raw_password)
                if encrypted:
                    self.encrypted_login_password = encrypted
                    self.save(update_fields=["encrypted_login_password"])
        return valid

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def has_real_email(self):
        return bool(self.email) and not self.email.endswith("@" + INTERNAL_EMAIL_DOMAIN)

    @property
    def login_name(self):
        """What they type to sign in: their username, or their email."""
        return self.username or self.email

    @property
    def is_school_admin(self):
        return self.role == self.Role.SCHOOL_ADMIN

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_individual(self):
        return self.role == self.Role.INDIVIDUAL

    @property
    def additional_levels_list(self):
        """The extra levels, unpacked from the stored ",Level 3,Level 6," form."""
        return [lvl for lvl in self.additional_levels.split(",") if lvl]

    @property
    def all_levels(self):
        """Every level this person may open: their main one first, then any
        others they also teach, in the site's own level order. Empty means
        every level — an individual learner, a school admin, or a school
        account with no level set yet. This is what apps.accounts.access
        gates on, so a teacher given several levels here can open all of
        them."""
        from apps.echospell.models import LEVEL_NAME_CHOICES

        order = [value for value, _label in LEVEL_NAME_CHOICES]
        levels = dict.fromkeys(([self.level] if self.level else []) + self.additional_levels_list)
        return sorted(levels, key=lambda v: order.index(v) if v in order else len(order))

    @property
    def level_display(self):
        """How their level(s) read on a page: "Level 3", or, for a teacher
        given more than one, "Level 1, Level 3 and Level 6"."""
        levels = self.all_levels
        if not levels:
            return ""
        if len(levels) == 1:
            return levels[0]
        return ", ".join(levels[:-1]) + f" and {levels[-1]}"


class DeviceLogin(models.Model):
    """One account remembered on one device for the account switcher
    (apps/accounts/switcher.py), e.g. a parent's device shared by two
    children. The device keeps the key in a signed cookie; only its hash is
    stored here. It stops working when it's removed, when the account's
    password changes (auth_hash no longer matches) or the account is
    switched off."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_logins")
    key_hash = models.CharField(max_length=64, unique=True)
    auth_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_used_at"]

    def __str__(self):
        return f"{self.user} on a device"


class DashboardCardImage(models.Model):
    """Optional image backgrounds for individual learner dashboard cards."""

    CARD_KEYS = (
        ("progress-echospell", "EchoSpell progress card"),
        ("progress-etiquette", "Etiquette Advantage progress card"),
        ("progress-academy", "44 Academy progress card"),
        ("progress-tricks", "Tricks to Sound Fluent progress card"),
        ("progress-tutor", "AI Reading Tutor progress card"),
        ("progress-modules", "My Modules progress card"),
        ("tool-learning-modules", "Learning Modules tool card"),
        ("tool-echospell", "EchoSpell tool card"),
        ("tool-quick-words", "Quick Words tool card"),
        ("tool-assessments", "Assessments tool card"),
        ("tool-clash", "Diction Clash tool card"),
        ("tool-tutor", "AI Reading Tutor tool card"),
        ("tool-daily-practice", "Daily Practice tool card"),
        ("tool-academy", "44 Academy tool card"),
        ("tool-tricks", "Tricks to Sound Fluent tool card"),
        ("tool-reading-club", "Reading Club tool card"),
        ("tool-reference-library", "Reference Library tool card"),
    )

    key = models.CharField(max_length=40, primary_key=True, choices=CARD_KEYS, editable=False)
    image = models.ImageField(
        upload_to="dashboard/cards/", blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
        help_text="Upload an image from this device. Wide images work best. Leave empty to use the card's built-in colors.",
    )

    class Meta:
        ordering = ["key"]
        verbose_name = "dashboard card image"
        verbose_name_plural = "dashboard card images"

    @property
    def label(self):
        return self.get_key_display()

    def __str__(self):
        return self.get_key_display()

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        super().save(*args, **kwargs)
        if previous and previous.image and previous.image.name != (self.image.name if self.image else ""):
            previous.image.storage.delete(previous.image.name)
