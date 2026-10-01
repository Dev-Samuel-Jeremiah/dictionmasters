"""
Four ways to get an account:

- SchoolRegistrationForm: creates a School and its first user, the
  school admin, together.
- SchoolTeamRegistrationForm: creates a school, admin, and its first
  teachers and students together.
- IndividualRegistrationForm: an adult learner, no school.
- StudentRegistrationForm: a pupil joining with their school's code and
  paying for their own access.
- TeacherRegistrationForm: a teacher joining with their school's code.

Every registration also asks how to begin: the free trial, or paying for
a plan now (see StartChoiceMixin). Plans and prices come from billing.

Login is handled by EmailAuthenticationForm, a thin wrapper over
Django's AuthenticationForm. It accepts an email address or an account
username and carries the same field styling as everything else.
"""

import secrets

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from apps.schools.models import AccessCode, School

from .models import User

# Said the same way on every form that sets a password, and matching what
# the site actually checks (see AUTH_PASSWORD_VALIDATORS): eight characters
# or more, not all numbers, not one of the common ones, and not made from
# the name or email already on the form. The registration pages turn this
# into a live check as the person types (static/js/password_strength.js);
# without JavaScript it is still shown here.
PASSWORD_HELP = (
    "8 characters or more, not all numbers, and not an easy one to guess. "
    "Three small words and a number work well — like “mango river 47” or “Blue-Gate-8”."
)


USERNAME_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$"


def unique_username(first, last=""):
    """ada.okafor, then ada.okafor2, ada.okafor3... never one that's taken."""
    import re as _re

    from django.utils.text import slugify

    base = ".".join(p for p in (slugify(first), slugify(last)) if p).replace("-", "")[:34] or "student"
    base = _re.sub(r"[^a-z0-9.]", "", base) or "student"
    name, i = base, 1
    while User.objects.filter(username__iexact=name).exists():
        i += 1
        name = f"{base}{i}"
    return name


def internal_email(username):
    from .models import INTERNAL_EMAIL_DOMAIN

    return f"{username.lower()}@{INTERNAL_EMAIL_DOMAIN}"


class StyledFormMixin:
    """Adds a consistent CSS class to every field, so templates don't
    have to repeat `class="field-input"` on every single widget."""

    def _style_fields(self):
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            css = "field-input"
            if isinstance(field.widget, (forms.CheckboxInput,)):
                css = "field-checkbox"
            field.widget.attrs["class"] = f"{existing} {css}".strip()


class StartChoiceMixin:
    """"Start my free trial" or "Pay now" — and if paying, which plan.

    Subclasses call _add_start_fields() with the plans to offer as
    (value, label) pairs. `start` and `plan` are left out of
    account_fields, so the template can lay the choice out on its own."""

    START_FIELDS = ("start", "plan", "promo_code")

    def _add_start_fields(self, plan_choices, plan_label="Plan"):
        from apps.billing.models import BillingSettings

        settings_ = BillingSettings.load()
        self.paywall = settings_.paywall_enabled
        self.trial_days = settings_.trial_days if settings_.paywall_enabled else 0
        options = []
        if self.trial_days or not self.paywall:
            options.append(("trial", f"Start my {self.trial_days}-day free trial" if self.trial_days else "Start learning"))
        if self.paywall and plan_choices:
            options.append(("pay", "Pay now"))
        self.fields["start"] = forms.ChoiceField(choices=options, widget=forms.RadioSelect, initial=options[0][0] if options else "")
        self.fields["start"].required = bool(options)
        self.fields["plan"] = forms.ChoiceField(
            choices=[("", "Choose a plan")] + list(plan_choices), required=False, label=plan_label,
        )
        self.fields["plan"].widget.attrs["class"] = "field-input"
        # A promo code takes money off the plan at checkout (apps/billing).
        self.fields["promo_code"] = forms.CharField(
            required=False, max_length=20, label="Promo code (optional)",
            widget=forms.TextInput(attrs={"class": "field-input", "placeholder": "e.g. JDM201",
                                          "autocapitalize": "characters", "autocomplete": "off"}),
        )

    @property
    def account_fields(self):
        return [field for field in self if field.name not in self.START_FIELDS]

    def _clean_start(self, cleaned):
        if cleaned.get("start") == "pay" and not cleaned.get("plan"):
            self.add_error("plan", "Choose the plan you'd like to pay for.")
        code = (cleaned.get("promo_code") or "").strip().upper()
        if code:
            from apps.billing.models import Plan
            from apps.billing.services import find_promo

            cleaned["promo_code"] = code
            plan = Plan.objects.filter(slug=cleaned.get("plan")).first() if cleaned.get("plan") else None
            _, refusal = find_promo(code, plan=plan)
            if refusal:
                self.add_error("promo_code", refusal)
        if not self.fields["start"].choices:
            cleaned["start"] = "trial"
        return cleaned


def _plan_choices(audience):
    from apps.billing.models import Plan
    from apps.billing.templatetags.billing import naira

    return [
        (plan.slug, f"{plan.band_label + ' · ' if plan.band_label else ''}{plan.name} — {naira(plan.price)}")
        for plan in Plan.objects.filter(is_active=True, audience=audience)
    ]


class SchoolRegistrationForm(StartChoiceMixin, StyledFormMixin, forms.Form):
    school_name = forms.CharField(label="School name", max_length=255)
    school_email = forms.EmailField(label="School email")
    school_phone = forms.CharField(label="School phone number", max_length=20, required=False)
    school_address = forms.CharField(label="School address", max_length=255, required=False)

    first_name = forms.CharField(label="Your first name", max_length=150)
    last_name = forms.CharField(label="Your last name", max_length=150, required=False)
    email = forms.EmailField(label="Your email (used to sign in)")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self._add_start_fields(_plan_choices("school"), plan_label="Plan (by number of teachers)")
        # The plan sets how many teachers can join, from the free trial on.
        if len(self.fields["plan"].choices) > 1:
            self.fields["plan"].required = True
            self.fields["plan"].help_text = "How many teachers can join your school. You can move to a bigger plan later."

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account already exists with this email.")
        return email

    def clean_school_email(self):
        return self.cleaned_data["school_email"].lower().strip()

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Those passwords don't match.")
        return self._clean_start(cleaned)

    def save(self):
        school = School.objects.create(
            name=self.cleaned_data["school_name"],
            email=self.cleaned_data["school_email"],
            phone=self.cleaned_data["school_phone"],
            address=self.cleaned_data["school_address"],
        )
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=User.Role.SCHOOL_ADMIN,
            school=school,
        )
        return user


class SchoolTeamRegistrationForm(StyledFormMixin, forms.Form):
    """School onboarding form for creating the school and its first team."""

    school_name = forms.CharField(label="School name", max_length=255)
    school_email = forms.EmailField(label="School contact email (optional)", required=False)
    school_phone = forms.CharField(label="School phone number", max_length=120, required=False)
    school_address = forms.CharField(label="School address", max_length=255, required=False)

    admin_first_name = forms.CharField(label="First name", max_length=150)
    admin_last_name = forms.CharField(label="Last name", max_length=150)
    admin_email = forms.EmailField(label="Admin email", max_length=254)

    def __init__(self, *args, **kwargs):
        from apps.billing.models import Plan

        super().__init__(*args, **kwargs)
        plans = Plan.objects.filter(is_active=True, audience=Plan.AUDIENCE_SCHOOL).order_by("max_units", "name")
        has_plans = plans.exists()
        self.fields["plan"] = forms.ModelChoiceField(
            queryset=plans,
            empty_label="Choose a school plan" if has_plans else None,
            required=has_plans,
            label="School plan",
        )
        from apps.billing.templatetags.billing import naira

        self.fields["plan"].label_from_instance = lambda plan: (
            f"{plan.name}{' · ' + plan.band_label if plan.band_label else ''} — {naira(plan.price)}"
        )
        if not has_plans:
            self.fields["plan"].help_text = "No active school plans are available right now. You can choose a plan after registration."
        else:
            self.fields["plan"].help_text = "Your plan sets how many teachers can be registered. You can activate payment from the school dashboard."
        self._style_fields()

    def clean_school_name(self):
        from apps.schools.models import School

        name = " ".join(self.cleaned_data["school_name"].split())
        if School.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("A school with this name is already registered. Please contact Diction Masters for help.")
        return name

    def clean_school_email(self):
        return self.cleaned_data["school_email"].strip().lower()

    def clean_admin_first_name(self):
        return " ".join(self.cleaned_data["admin_first_name"].split())

    def clean_admin_last_name(self):
        return " ".join(self.cleaned_data["admin_last_name"].split())

    def clean_admin_email(self):
        email = self.cleaned_data["admin_email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

class SchoolTeamMemberForm(StyledFormMixin, forms.Form):
    """One teacher or student in the new school's initial roster."""

    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    level = forms.ChoiceField(label="Level", choices=[])
    email = forms.EmailField(label="Email (optional)", max_length=254, required=False)

    def __init__(self, *args, kind="student", **kwargs):
        from apps.echospell.models import LEVEL_NAME_CHOICES

        super().__init__(*args, **kwargs)
        self.kind = kind
        self.fields["level"].choices = [("", "Choose a level")] + list(LEVEL_NAME_CHOICES)
        self.fields["level"].label = "Level taught" if kind == "teacher" else "Student level"
        self.fields["first_name"].widget.attrs["placeholder"] = "First name"
        self.fields["first_name"].widget.attrs["aria-label"] = "First name"
        self.fields["last_name"].widget.attrs["placeholder"] = "Last name"
        self.fields["last_name"].widget.attrs["aria-label"] = "Last name"
        self.fields["level"].widget.attrs["aria-label"] = self.fields["level"].label
        self.fields["email"].widget.attrs["placeholder"] = "Email (optional)"
        self.fields["email"].widget.attrs["aria-label"] = "Email (optional)"
        self._style_fields()

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split())

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


class IndividualRegistrationForm(StartChoiceMixin, StyledFormMixin, forms.Form):
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self._add_start_fields(_plan_choices("individual"))

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account already exists with this email.")
        return email

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Those passwords don't match.")
        return self._clean_start(cleaned)

    def save(self):
        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=User.Role.INDIVIDUAL,
        )


class StudentRegistrationForm(StyledFormMixin, forms.Form):
    """A pupil joining their school with its code. The school's plan covers
    them, just like its teachers, so there's nothing to pay."""

    school_code = forms.CharField(
        label="School code", max_length=16,
        help_text="Your school's code, e.g. DM-ABC234. Ask your teacher if you don't have it.",
    )
    level = forms.ChoiceField(label="Your class level", choices=[])
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    username = forms.CharField(
        label="Username", max_length=40,
        help_text="What you'll sign in with, e.g. ada.okafor. Letters, numbers, dots and dashes.",
    )
    email = forms.EmailField(label="Email (optional)", required=False, help_text="A parent's email is fine. You don't need one to sign in.")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        from apps.echospell.models import LEVEL_NAME_CHOICES

        super().__init__(*args, **kwargs)
        self.fields["level"].choices = [("", "Choose your level")] + LEVEL_NAME_CHOICES
        self._style_fields()
        self.fields["school_code"].widget.attrs.update({"autocapitalize": "characters", "autocomplete": "off"})
        self._school = None

    def clean_school_code(self):
        code = self.cleaned_data["school_code"].strip().upper()
        if code and not code.startswith("DM-"):
            code = f"DM-{code}"
        school = School.objects.filter(code=code).first()
        if school is None:
            raise forms.ValidationError("That school code isn't recognised. Check it with your teacher.")
        if school.students_full:
            raise forms.ValidationError(
                f"{school.name} has reached the number of students it can register "
                f"({school.max_students}). Please ask your school to contact Diction Masters for more places."
            )
        self._school = school
        return code

    def clean_username(self):
        import re as _re

        name = self.cleaned_data["username"].strip()
        if not _re.match(USERNAME_RE, name):
            raise forms.ValidationError("Use 3 to 40 letters or numbers; dots, dashes and underscores are fine. No spaces.")
        if User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError(f"“{name}” is taken. Try adding a number, e.g. {name}{secrets.randbelow(90) + 10}.")
        return name.lower()

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").lower().strip()
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account already exists with this email.")
        return email

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Those passwords don't match.")
        return cleaned

    def save(self):
        return User.objects.create_user(
            email=self.cleaned_data["email"] or internal_email(self.cleaned_data["username"]),
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=User.Role.STUDENT,
            school=self._school,
            level=self.cleaned_data["level"],
        )


class TeacherRegistrationForm(StyledFormMixin, forms.Form):
    """A teacher joining their school with the school's code. They choose
    the level they teach, and see only that level's work. The school's
    plan sets how many teachers can join; once it's full, nobody else can
    until the school moves to a bigger plan. A one-time code a school
    admin handed out before school codes did this is still accepted."""

    school_code = forms.CharField(
        label="School code", max_length=16,
        help_text="Your school's code, e.g. DM-ABC234. Your school admin has it.",
    )
    level = forms.ChoiceField(
        label="The level you teach", choices=[], required=False,
        help_text="You'll see this level's lessons and your students' work at this level.",
    )
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        from apps.echospell.models import LEVEL_NAME_CHOICES

        super().__init__(*args, **kwargs)
        self.fields["level"].choices = [("", "Choose your level")] + LEVEL_NAME_CHOICES
        self._style_fields()
        self.fields["school_code"].widget.attrs.update({"autocapitalize": "characters", "autocomplete": "off"})
        self._school = None
        self._access_code = None

    def clean_school_code(self):
        raw = self.cleaned_data["school_code"].strip().upper()
        legacy = AccessCode.objects.select_related("school").filter(code=raw, role=AccessCode.Role.TEACHER).first()
        if legacy is not None:
            if legacy.is_used:
                raise forms.ValidationError("That one-time code has already been used. Use your school's code instead.")
            self._access_code, school = legacy, legacy.school
        else:
            code = raw if raw.startswith("DM-") else f"DM-{raw}"
            school = School.objects.filter(code=code).first()
            if school is None:
                raise forms.ValidationError("That school code isn't recognised. Check it with your school admin.")
            raw = code
        if school.teachers_full:
            raise forms.ValidationError(
                f"{school.name} has reached its limit of {school.teacher_limit} teacher"
                f"{'' if school.teacher_limit == 1 else 's'} on its current plan, so no more teachers can join. "
                "Please ask your school admin to upgrade to a bigger plan."
            )
        self._school = school
        return raw

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account already exists with this email.")
        return email

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Those passwords don't match.")
        # An old one-time code already carries a level; otherwise it's chosen here.
        if not cleaned.get("level") and not (self._access_code and self._access_code.level):
            self.add_error("level", "Choose the level you teach.")
        return cleaned

    def save(self):
        level = self.cleaned_data.get("level") or (self._access_code.level if self._access_code else "")
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=User.Role.TEACHER,
            school=self._school,
            level=level,
        )
        if self._access_code is not None:
            self._access_code.mark_used_by(user)
        return user


class EmailAuthenticationForm(StyledFormMixin, AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _(
            "Please enter a correct email or username and password. "
            "Passwords are case-sensitive."
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email or username"
        self.fields["username"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "username", "type": "text"})
        self._style_fields()

    def clean_username(self):
        # Sign in with an email, or with a username (students). Either is
        # matched without regard to case and turned into the stored email,
        # which Django's normal authentication backend then checks. This also
        # lets accounts created before emails were stored in lowercase in.
        typed = self.cleaned_data["username"].strip()
        if "@" not in typed:
            by_name = User.objects.filter(username__iexact=typed).values_list("email", flat=True).first()
            if by_name:
                return by_name
        stored_email = User.objects.filter(email__iexact=typed).values_list("email", flat=True).first()
        return stored_email or typed.lower()
