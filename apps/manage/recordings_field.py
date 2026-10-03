"""The "Narration recordings" field on a Diction Library item's form:
choose many recordings at once ("Chapter five", "Chapter 4", "Page 121 to
124" ...). Each becomes a chapter of the book's read-aloud, put in order by
the chapter or page in its name — whatever order they were chosen in — and
matched to that part of the book's text (apps/diction_library/narration.py).
Ones already there are listed in reading order and can be ticked to remove.
"""

from django import forms
from django.core.validators import FileExtensionValidator
from django.utils.html import format_html

from apps.diction_library import narration
from apps.diction_library.models import LibraryRecording

ADD = "recordings"
REMOVE = "remove_recordings"
SOUNDS = ["mp3", "m4a", "wav", "ogg", "aac"]
MAX_BYTES = 200 * 1024 * 1024


class ManyFiles(forms.ClearableFileInput):
    allow_multiple_selected = True


class ManyFilesField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", ManyFiles(attrs={"accept": "audio/*", "class": "cr-many-files"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        cleaned = [single(f, initial) for f in files]
        for f in cleaned:
            FileExtensionValidator(SOUNDS)(f)
            if f.size > MAX_BYTES:
                raise forms.ValidationError(f"“{f.name}” is larger than 200 MB.")
        return cleaned


def add_recordings_field(form, obj):
    form.fields.pop("narration_file", None)            # the old single recording, now one of many
    form.fields[ADD] = ManyFilesField(
        required=False, label="Narration recordings (optional)",
        help_text="Choose all of the book’s recordings at once — e.g. “Chapter five”, “Chapter 4”, “Page 121 to 124”. "
                  "Each becomes a chapter, put in order by the chapter or page in its name, with the words of that "
                  "chapter or those pages highlighted as it plays. Leave empty and a read-aloud is made "
                  "automatically from the book’s text.",
    )
    # Where the old single "Narration" field was: just after the book's file.
    order = [name for name in form.fields if name != ADD]
    order.insert(order.index("file") + 1 if "file" in order else len(order), ADD)
    form.order_fields(order)
    existing = narration._recordings(obj) if obj is not None and obj.pk else []
    if existing:
        form.fields[REMOVE] = forms.MultipleChoiceField(
            required=False, label=f"Recordings on this book ({len(existing)}) — in reading order",
            help_text="Tick any to remove, then save.",
            choices=[(str(r.pk), format_html("<strong>{}</strong> <span class='cr-help'>{}</span>",
                                             narration.recording_title(r.name), r.name)) for r in existing],
            widget=forms.CheckboxSelectMultiple(attrs={"class": "cr-recordings"}),
        )
        # Keep it next to the upload, not at the bottom of the form.
        order = list(form.fields)
        order.remove(REMOVE)
        order.insert(order.index(ADD) + 1, REMOVE)
        form.order_fields(order)


def save_recordings(form, saved):
    """After saved.save(): add the new recordings, remove the ticked ones,
    and rebuild the read-aloud's chapters from them."""
    added = form.cleaned_data.get(ADD) or []
    removing = form.cleaned_data.get(REMOVE) or []
    for upload in added:
        LibraryRecording.objects.create(item=saved, name=narration.name_from_file(upload.name), audio_file=upload)
    for recording in LibraryRecording.objects.filter(item=saved, pk__in=removing):
        recording.delete()
    if added or removing:
        narration.refresh(saved)
    return len(added), len(removing)
