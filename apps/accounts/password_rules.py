"""
How strong a password has to be.

For everyone — learners, parents, teachers, school admins — a password just
needs MIN_LENGTH characters: simple ones are fine, so nobody is stopped at
sign-up. Staff are different: a staff account opens the control room and
can change the whole site, so for them StaffPasswordValidator also applies
Django's full checks (eight or more characters, not common, not only
numbers, not like their name or email). Wired up in AUTH_PASSWORD_VALIDATORS.
"""

from django.contrib.auth import password_validation

MIN_LENGTH = 6
STAFF_VALIDATORS = [
    password_validation.UserAttributeSimilarityValidator(),
    password_validation.MinimumLengthValidator(min_length=8),
    password_validation.CommonPasswordValidator(),
    password_validation.NumericPasswordValidator(),
]


class StaffPasswordValidator:
    """The full checks, for staff accounts only."""

    def validate(self, password, user=None):
        if user is None or not getattr(user, "is_staff", False):
            return
        password_validation.validate_password(password, user, password_validators=STAFF_VALIDATORS)

    def get_help_text(self):
        return "Staff accounts need 8 characters or more, not common, not only numbers and not like your name."
