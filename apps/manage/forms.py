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
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()
            if isinstance(widget, forms.DateInput):
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
