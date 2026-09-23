from django import forms

from .models import LibraryItem


class LibraryItemForm(forms.ModelForm):
    class Meta:
        model = LibraryItem
        fields = ["title", "kind", "summary", "description", "file", "external_url", "is_published", "order"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "summary": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        existing_file = bool(self.instance and self.instance.pk and self.instance.file)
        if not (cleaned.get("file") or existing_file or cleaned.get("external_url") or cleaned.get("description")):
            raise forms.ValidationError("Add a file, a link, or some written content before saving.")
        return cleaned
