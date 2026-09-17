"""
Three ways to get an account, three forms:

- SchoolRegistrationForm: creates a School and its first user, the
  school admin, together.
- IndividualRegistrationForm: a standalone learner, no school.
- JoinWithCodeForm: a teacher or student redeeming a code a school
  admin generated for them.

Login is handled by EmailAuthenticationForm, a thin wrapper over
Django's AuthenticationForm so it speaks "email" instead of
"username" and carries the same field styling as everything else.
"""

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.schools.models import AccessCode, School

from .models import User


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


class SchoolRegistrationForm(StyledFormMixin, forms.Form):
    school_name = forms.CharField(label="School name", max_length=255)
    school_email = forms.EmailField(label="School email")
    school_phone = forms.CharField(label="School phone number", max_length=20, required=False)
    school_address = forms.CharField(label="School address", max_length=255, required=False)

    first_name = forms.CharField(label="Your first name", max_length=150)
    last_name = forms.CharField(label="Your last name", max_length=150, required=False)
    email = forms.EmailField(label="Your email (used to sign in)")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

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
        return cleaned

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


class IndividualRegistrationForm(StyledFormMixin, forms.Form):
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

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
        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=User.Role.INDIVIDUAL,
        )


class JoinWithCodeForm(StyledFormMixin, forms.Form):
    code = forms.CharField(
        label="Your code",
        max_length=10,
        help_text="The code your school admin gave you.",
    )
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
