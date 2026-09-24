"""Bulk entry forms for Tricks assessment questions."""

from django import forms
from django.forms import BaseFormSet, formset_factory

from apps.echospell.activity_kinds import MODE_CHOICE, MODE_RECORD

from .forms import ControlFormMixin


class BulkQuestionForm(ControlFormMixin, forms.Form):
    prompt = forms.CharField(
        required=False,
        label="Question / prompt",
        help_text="What the learner sees. Required for this activity type.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    answer = forms.CharField(
        required=False,
        label="Correct answer",
        help_text="Separate equally correct answers with |, for example colour|color.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    options = forms.CharField(
        required=False,
        label="Answer options",
        help_text="For multiple choice, enter one option per line.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    hint = forms.CharField(required=False, label="Hint", max_length=200)
    audio_url = forms.URLField(required=False, label="Audio URL")
    audio_file = forms.FileField(required=False, label="Audio file")
    image = forms.ImageField(required=False, label="Question image")

    def __init__(self, *args, kind_spec, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind_spec = kind_spec
        used = set(kind_spec.item_fields)
        if kind_spec.needs_audio:
            used.update(("audio_url", "audio_file"))
        if kind_spec.uses_image:
            used.add("image")
        self.fields = {name: field for name, field in self.fields.items() if name in used}
        if "prompt" in self.fields:
            self.fields["prompt"].help_text = kind_spec.prompt_help or self.fields["prompt"].help_text
        if "answer" in self.fields:
            self.fields["answer"].help_text = kind_spec.answer_help or self.fields["answer"].help_text
        if "options" in self.fields:
            self.fields["options"].help_text = kind_spec.options_help or self.fields["options"].help_text
        if kind_spec.uses_prompt:
            self.fields["prompt"].required = True
        if kind_spec.mode != MODE_RECORD:
            self.fields["answer"].required = True
        if kind_spec.mode == MODE_CHOICE:
            self.fields["options"].required = True
        if kind_spec.uses_image:
            self.fields["image"].required = True
        self.polish()

    def clean(self):
        cleaned = super().clean()
        if not self.has_changed():
            return cleaned

        if self.kind_spec.needs_audio and not (
            cleaned.get("audio_file") or cleaned.get("audio_url")
        ):
            self.add_error("audio_url", "Add an audio file or an audio URL for this question.")
        return cleaned


class BulkQuestionFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        populated = [
            form for form in self.forms
            if form.has_changed() and not form.cleaned_data.get("DELETE", False)
        ]
        if not populated:
            raise forms.ValidationError("Enter at least one question before saving.")


def question_formset(kind_spec, data=None, files=None):
    """Build a type-aware batch of five rows, with room to add up to 100."""
    factory = formset_factory(
        BulkQuestionForm,
        formset=BulkQuestionFormSet,
        extra=5,
        max_num=100,
        validate_max=True,
        can_delete=True,
    )
    return factory(
        data=data,
        files=files,
        prefix="questions",
        form_kwargs={"kind_spec": kind_spec},
    )
