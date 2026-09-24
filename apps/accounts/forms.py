"""
Four ways to get an account:

- SchoolRegistrationForm: creates a School and its first user, the
  school admin, together.
- IndividualRegistrationForm: an adult learner, no school.
- StudentRegistrationForm: a pupil joining with their school's code and
  paying for their own access.
- JoinWithCodeForm: a teacher redeeming a code their school admin made.

Every registration also asks how to begin: the free trial, or paying for
a plan now (see StartChoiceMixin). Plans and prices come from billing.

Login is handled by EmailAuthenticationForm, a thin wrapper over
Django's AuthenticationForm so it speaks "email" instead of
"username" and carries the same field styling as everything else.
"""

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


def _school_is_full(school):
    """A school on a paid plan whose teacher tier is already full."""
    from django.utils import timezone

    subscription = getattr(school, "subscription", None)
    try:
        plan = subscription.plan if subscription and subscription.paid_until and subscription.paid_until > timezone.now() else None
    except Exception:
        plan = None
    if not plan or not plan.max_units:
        return False
    return school.members.filter(role=User.Role.TEACHER).count() >= plan.max_units


class StudentRegistrationForm(StartChoiceMixin, StyledFormMixin, forms.Form):
    """A pupil signing up at home with their school's code. They choose the
    free trial or pay for themselves; the per-child price depends on how
    many children their school has enrolled."""

    school_code = forms.CharField(
        label="School code", max_length=16,
        help_text="Your school's code, e.g. DM-ABC234. Ask your teacher if you don't have it.",
    )
    level = forms.ChoiceField(label="Your class level", choices=[])
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email", help_text="A parent's email is fine.")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        from apps.billing.models import Plan
        from apps.echospell.models import LEVEL_NAME_CHOICES

        super().__init__(*args, **kwargs)
        self.fields["level"].choices = [("", "Choose your level")] + LEVEL_NAME_CHOICES
        self._style_fields()
        self.fields["school_code"].widget.attrs.update({"autocapitalize": "characters", "autocomplete": "off"})
        periods = []
        for plan in Plan.objects.filter(is_active=True, audience=Plan.AUDIENCE_STUDENT).order_by("duration_days"):
            if plan.name not in [value for value, _label in periods]:
                periods.append((plan.name, plan.name))
        self._add_start_fields(periods, plan_label="How long to pay for")
        self._school = None

    def clean_school_code(self):
        code = self.cleaned_data["school_code"].strip().upper()
        if code and not code.startswith("DM-"):
            code = f"DM-{code}"
        school = School.objects.filter(code=code).first()
        if school is None:
            raise forms.ValidationError("That school code isn't recognised. Check it with your teacher.")
        self._school = school
        return code

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
            role=User.Role.STUDENT,
            school=self._school,
            level=self.cleaned_data["level"],
        )

    def chosen_plan(self, user):
        """The per-child plan for the chosen period, priced for the school's
        enrolment now that this student is counted in it."""
        from apps.billing.access import plans_for

        period = self.cleaned_data.get("plan")
        return next((plan for plan, ok, _why in plans_for(user) if ok and plan.name == period), None)


class JoinWithCodeForm(StyledFormMixin, forms.Form):
    code = forms.CharField(
        label="Your code",
        max_length=10,
        help_text="The code your school admin gave you.",
    )
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, help_text=PASSWORD_HELP)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        self._access_code = None

    def clean_code(self):
        raw = self.cleaned_data["code"].strip().upper()
        try:
            access_code = AccessCode.objects.select_related("school").get(code=raw)
        except AccessCode.DoesNotExist:
            raise forms.ValidationError("That code isn't recognised. Double-check it with your school.")
        if access_code.is_used:
            raise forms.ValidationError("That code has already been used.")
        if access_code.role == AccessCode.Role.STUDENT:
            raise forms.ValidationError(
                "Students now join with their school's code on the student sign-up page, "
                "where they choose a free trial or pay for their own access."
            )
        if _school_is_full(access_code.school):
            raise forms.ValidationError(
                "Your school has reached the number of teachers its plan allows. "
                "Please ask your school admin to move to a bigger plan."
            )
        self._access_code = access_code
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
        return cleaned

    def save(self):
        access_code = self._access_code
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=access_code.role,
            school=access_code.school,
            # The code decides the level; it is never typed by the
            # person joining.
            level=access_code.level,
        )
        access_code.mark_used_by(user)
        return user


class EmailAuthenticationForm(StyledFormMixin, AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _(
            "Please enter a correct email address and password. "
            "Passwords are case-sensitive."
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def clean_username(self):
        # Registration stores email addresses in lowercase. Resolve the
        # submitted address without regard to case, then pass the exact
        # stored value to Django's normal authentication backend. This also
        # lets accounts created before that convention keep signing in.
        email = self.cleaned_data["username"].strip()
        stored_email = User.objects.filter(email__iexact=email).values_list("email", flat=True).first()
        return stored_email or email.lower()
