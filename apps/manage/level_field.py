"""The "Levels" field on the control room's user and profile forms:
everyone has one level by default, but a teacher can be given several —
Level 1, Level 3 and Level 6, say — by ticking more than one here. That
is what apps.accounts.access reads to decide what they may open.

The real fields are User.level (their main one — used wherever the site
shows a single level: the dashboard, a joining code's starting level) and
User.additional_levels (the rest); this field edits both together as one
tick-list and splits it back apart on save.

The same tick-list edits a `levels` field on content made for several
levels, or a tool kept for some (screens with "content_levels"):
add_content_levels_field / save_content_levels, stored as
",Level 1,Level 2," by apps.accounts.access.pack_levels.
"""

from django import forms

from apps.echospell.models import LEVEL_NAME_CHOICES

FIELD = "levels_taught"
LEVEL_ORDER = [value for value, _label in LEVEL_NAME_CHOICES]


def add_levels_field(form, obj):
    """Replace the plain "level" field with a tick-list of every level."""
    form.fields.pop("level", None)
    form.fields.pop("additional_levels", None)
    current = list(obj.all_levels) if obj is not None and obj.pk else []
    form.fields[FIELD] = forms.MultipleChoiceField(
        choices=LEVEL_NAME_CHOICES, required=False, initial=current,
        label="Levels",
        help_text="Every level they teach or study. Most people have just one; tick more for a teacher "
                  "who covers several. Leave every box empty to let them see every level (an individual "
                  "learner or a school admin).",
        widget=forms.CheckboxSelectMultiple(attrs={"class": "cr-levels"}),
    )


def save_levels(form, saved):
    """After saved.save(): split the ticked levels into User.level (the
    first, in the site's own order) and User.additional_levels (the
    rest, stored as ",Level 3,Level 6,")."""
    if FIELD not in form.cleaned_data:
        return
    chosen = sorted(set(form.cleaned_data[FIELD]),
                    key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else len(LEVEL_ORDER))
    saved.level = chosen[0] if chosen else ""
    saved.additional_levels = ("," + ",".join(chosen[1:]) + ",") if len(chosen) > 1 else ""
    saved.save(update_fields=["level", "additional_levels"])


CONTENT_FIELD = "levels"


def add_content_levels_field(form, obj):
    """Show a content record's `levels` as a tick-list of every level."""
    from apps.accounts.access import unpack_levels

    if CONTENT_FIELD not in form.fields:
        return
    help_text = form.fields[CONTENT_FIELD].help_text
    form.fields[CONTENT_FIELD] = forms.MultipleChoiceField(
        choices=LEVEL_NAME_CHOICES, required=False,
        initial=unpack_levels(obj.levels) if obj is not None and obj.pk else [],
        label="Levels", help_text=help_text,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "cr-levels"}),
    )


def save_content_levels(form, saved):
    """After saved.save(): store the ticked levels as ",Level 1,Level 2,"."""
    from apps.accounts.access import pack_levels

    if CONTENT_FIELD not in form.cleaned_data:
        return
    saved.levels = pack_levels(form.cleaned_data[CONTENT_FIELD])
    saved.save(update_fields=["levels"])
