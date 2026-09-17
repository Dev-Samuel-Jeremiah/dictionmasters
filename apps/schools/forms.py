from django import forms

from apps.echospell.models import LEVEL_NAME_CHOICES

from .models import AccessCode


class GenerateAccessCodeForm(forms.Form):
    role = forms.ChoiceField(choices=AccessCode.Role.choices, widget=forms.RadioSelect)
    level = forms.ChoiceField(
        choices=[("", "Choose a level")] + LEVEL_NAME_CHOICES,
        label="Level",
        help_text="Whoever uses this code studies or teaches this level, and sees only its work.",
    )
    label = forms.CharField(
        max_length=100,
        required=False,
        label="Note (optional)",
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. Primary 5 — Mrs Okafor's class",
        }),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].widget.attrs["class"] = "field-input"
        self.fields["level"].widget.attrs["class"] = "field-input"
