"""
Forms that show only what an activity's type needs.

An activity's type (apps/echospell/activity_kinds.py) decides which
fields matter: a Sound sort needs its sorting boxes, a Dictation question
needs audio but no prompt, a Read aloud question has no answer. A screen
that sets "kind_fields" gets a guide for its form:

  "activity"  the activity form: fields follow the Activity type chosen
              on the page, as it changes.
  "item"      a question form: fields follow its activity's type. When the
              activity is already known the unused fields are left out of
              the form altogether; otherwise they follow the activity
              chosen on the page.

The page does the showing and hiding (static/js/manage_kind_fields.js);
this builds what it needs to know.
"""

from django import forms

from apps.echospell.activity_kinds import KINDS, LOCKABLE_ACTIVITY_FIELDS, LOCKABLE_ITEM_FIELDS, MODE_SORT, get_kind

ITEM_HELP = {"prompt": "prompt_help", "answer": "answer_help", "options": "options_help"}


def _summary(kind):
    return f"{kind.icon} {kind.label} ({kind.mode_label}): {kind.summary}"


def _item_rules(kind):
    help_texts = {field: getattr(kind, attr) for field, attr in ITEM_HELP.items() if getattr(kind, attr, "")}
    if kind.needs_audio:
        help_texts["audio_file"] = "The recording the learner listens to for this question."
    if kind.uses_image:
        help_texts["image"] = "The picture the learner names."
    return {"fields": kind.item_fields, "help": help_texts, "summary": _summary(kind)}


def guide(screen, form, obj=None, parent_obj=None):
    """What the form page needs to show only the right fields, or None."""
    which = screen.get("kind_fields")
    if which == "activity":
        return {
            "select": "kind", "managed": LOCKABLE_ACTIVITY_FIELDS,
            "by_value": {
                kind.slug: {"fields": kind.activity_fields, "summary": _summary(kind),
                            "placeholder": {"instructions": kind.instructions}}
                for kind in KINDS
            },
        }
    if which == "item":
        activity = getattr(obj, "activity", None) if obj else None
        activity = activity or parent_obj
        if activity is not None and activity.kind_spec:
            rules = _item_rules(activity.kind_spec)
            for name in LOCKABLE_ITEM_FIELDS:
                if name in form.fields and name not in rules["fields"]:
                    del form.fields[name]
            for name, text in rules["help"].items():
                if name in form.fields:
                    form.fields[name].help_text = text
            # A Sound sort's answer is one of its boxes: offer them, rather
            # than a blank box that has to be typed to match exactly.
            boxes = activity.bucket_list
            if activity.mode == MODE_SORT and boxes and "answer" in form.fields:
                current = form.initial.get("answer", "")
                choices = [("", "Choose its box…")] + [(box, box) for box in boxes]
                if current and current not in boxes:
                    choices.append((current, f"{current} (not one of the boxes)"))
                form.fields["answer"].widget = forms.Select(choices=choices, attrs={"class": "cr-input cr-select"})
                form.fields["answer"].required = True
                form.fields["answer"].help_text = "The box this word belongs in."
            return {"summary": rules["summary"]}
        if "activity" in form.fields:
            return {
                "select": "activity", "managed": LOCKABLE_ITEM_FIELDS,
                "by_value": {
                    str(activity.pk): _item_rules(get_kind(activity.kind))
                    for activity in form.fields["activity"].queryset if get_kind(activity.kind)
                },
            }
    return None
