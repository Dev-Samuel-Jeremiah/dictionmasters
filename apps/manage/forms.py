"""
Forms for the control room.

Every screen's form is built from its model, so a new field on a model
appears here without anything being written twice. The only work done
here is making the fields look and behave the way the rest of the site
does: roomy text boxes, real date pickers, and a file box that says what
is already uploaded.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db import models

from apps.assembly_recitals.audio_zip import AudioZipError as RecitalAudioZipError
from apps.assembly_recitals.audio_zip import inspect_audio_zip as inspect_recital_audio_zip
from apps.quick_words.audio_zip import AudioZipError, inspect_audio_zip
from apps.manage.rich_text import RichTextWidget, is_rich_text_field


class ControlFormMixin:
    """Consistent styling and sensible widgets for every field."""

    def polish(self):
        for name, field in self.fields.items():
            widget = field.widget
            css = "cr-input"
            if isinstance(widget, forms.CheckboxInput):
                css = "cr-check"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "cr-input cr-select"
            elif isinstance(widget, (forms.ClearableFileInput, forms.FileInput)):
                css = "cr-file"
            elif isinstance(widget, forms.Textarea):
                css = "cr-input cr-textarea"
                widget.attrs.setdefault("rows", 6)
                model = getattr(getattr(self, "_meta", None), "model", None)
                if is_rich_text_field(name, model):
                    field.widget = RichTextWidget(attrs={**widget.attrs, "rows": 10})
                    widget = field.widget
                    css = "cr-input cr-textarea dm-rich-text-source"
            widget.attrs["class"] = " ".join(dict.fromkeys(f"{widget.attrs.get('class', '')} {css}".split()))
            if isinstance(widget, forms.DateTimeInput):
                # A real date-and-time picker, e.g. to extend someone's access by hand.
                widget.input_type = "datetime-local"
                widget.format = "%Y-%m-%dT%H:%M"
                if hasattr(field, "input_formats"):
                    field.input_formats = ["%Y-%m-%dT%H:%M", *field.input_formats]
            elif isinstance(widget, forms.DateInput):
                widget.input_type = "date"


def build_form(model, fields=None, exclude_parent=None):
    """A form for one model. `exclude_parent` hides the link to the thing
    it belongs to, when you are already adding it inside that thing."""
    editable = [
        f.name for f in model._meta.get_fields()
        if getattr(f, "editable", False) and not f.auto_created and f.name not in {"id", "password"}
    ]
    chosen = [f for f in (fields or editable) if f in editable or fields]
    if exclude_parent and exclude_parent in chosen:
        chosen = [f for f in chosen if f != exclude_parent]

    meta = type("Meta", (), {"model": model, "fields": chosen})

    def __init__(self, *args, **kwargs):
        forms.ModelForm.__init__(self, *args, **kwargs)
        self.polish()

    return type(
        f"{model.__name__}ControlForm",
        (ControlFormMixin, forms.ModelForm),
        {"Meta": meta, "__init__": __init__},
    )


class ControlLoginForm(ControlFormMixin, AuthenticationForm):
    """The control room's own sign-in: staff accounts only."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update({"autofocus": True, "autocomplete": "email"})
        self.polish()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "That account isn't an admin account. Learners sign in on the main site.",
                code="not_staff",
            )


class QuickWordAudioZipForm(forms.Form):
    audio_zip = forms.FileField(
        label="ZIP file of word audio",
        help_text=(
            "Each audio filename must be one word, such as about.mp3. "
            "Supported formats: MP3, M4A, AAC, WAV, OGG, OPUS, FLAC and WEBM. "
            "New words get IPA from IPA-Dict UK and definitions from OpenAI."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,application/zip", "class": "cr-file"}),
    )

    def clean_audio_zip(self):
        upload = self.cleaned_data["audio_zip"]
        try:
            self.audio_count = inspect_audio_zip(upload)
        except AudioZipError as error:
            raise forms.ValidationError(str(error)) from error
        return upload


class AssemblyRecitalAudioZipForm(forms.Form):
    audio_zip = forms.FileField(
        label="ZIP file of recital audio",
        help_text=(
            "Put files in folders named after their sections, for example "
            "Songs/Members of the family.mp3. The filename becomes the recital title. "
            "An existing recital with that title gets the new audio; otherwise one is created. "
            "Supported formats: MP3, M4A, AAC, WAV, OGG, OPUS, FLAC and WEBM."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,application/zip", "class": "cr-file"}),
    )

    def clean_audio_zip(self):
        upload = self.cleaned_data["audio_zip"]
        try:
            self.audio_count = inspect_recital_audio_zip(upload)
        except RecitalAudioZipError as error:
            raise forms.ValidationError(str(error)) from error
        return upload


class SchoolTrialForm(ControlFormMixin, forms.Form):
    """Billing settings: give one school its own free trial."""

    school = forms.ModelChoiceField(queryset=None, empty_label="Choose a school", label="School")
    length = forms.IntegerField(min_value=1, max_value=365, label="Trial length")
    unit = forms.ChoiceField(choices=[("days", "Days"), ("weeks", "Weeks"), ("months", "Months")], label="In", initial="months")

    reason = forms.CharField(
        max_length=120, label="Reason",
        help_text="They see this beside their free trial, e.g. \"Promo\" or \"Onboarded after old app issues\".",
    )

    def __init__(self, *args, **kwargs):
        from apps.schools.models import School

        super().__init__(*args, **kwargs)
        self.fields["school"].queryset = School.objects.order_by("name")
        self.fields["school"].label_from_instance = lambda s: (
            f"{s.name} ({s.code}) — own trial: {s.custom_trial_label}" if s.trial_length else f"{s.name} ({s.code})"
        )
        self.polish()


class LearnerTrialForm(ControlFormMixin, forms.Form):
    """Billing settings: give one individual learner their own free trial."""

    learner = forms.ModelChoiceField(queryset=None, empty_label="Choose a learner", label="Individual learner")
    length = forms.IntegerField(min_value=1, max_value=365, label="Trial length")
    unit = forms.ChoiceField(choices=[("days", "Days"), ("weeks", "Weeks"), ("months", "Months")], label="In", initial="months")

    reason = forms.CharField(
        max_length=120, label="Reason",
        help_text="They see this beside their free trial, e.g. \"Promo\" or \"Onboarded after old app issues\".",
    )

    def __init__(self, *args, **kwargs):
        from django.db.models import Q

        from apps.accounts.models import User

        super().__init__(*args, **kwargs)
        # Everyone who pays for themselves: adults, and any student with no school.
        self.fields["learner"].queryset = (
            User.objects.filter(is_staff=False, is_superuser=False)
            .filter(Q(role="individual") | Q(role="student", school__isnull=True))
            .order_by("first_name", "last_name", "email")
        )
        self.fields["learner"].label_from_instance = lambda u: f"{u.get_full_name() or u.email} ({u.email})"
        self.polish()


class EditTrialForm(ControlFormMixin, forms.Form):
    """Billing settings: change a school's or a learner's own trial."""

    MODES = [("add", "Add to the time left"), ("restart", "Start again from today")]
    reason = forms.CharField(max_length=120, label="Reason")
    length = forms.IntegerField(min_value=1, max_value=365, required=False, label="More time")
    unit = forms.ChoiceField(choices=[("days", "Days"), ("weeks", "Weeks"), ("months", "Months")], label="In", initial="days")
    mode = forms.ChoiceField(choices=MODES, initial="add", label="How", widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.polish()
