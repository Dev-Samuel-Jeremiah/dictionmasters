from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models

LOGO_MAX_BYTES = 2 * 1024 * 1024
FAVICON_MAX_BYTES = 512 * 1024


def _check_size(upload, limit):
    if upload and upload.size > limit:
        size = f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit // 1024} KB"
        raise ValidationError(f"That file is too big. Keep it under {size}.")


def validate_logo_size(upload):
    _check_size(upload, LOGO_MAX_BYTES)


def validate_favicon_size(upload):
    _check_size(upload, FAVICON_MAX_BYTES)


class SiteBranding(models.Model):
    """The site's logo and browser-tab icon, uploaded in the control room.

    There is only ever one row. Leave a field empty and the site keeps its
    built-in mark, so nothing breaks before anything is uploaded."""

    logo = models.ImageField(
        upload_to="branding/", blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"]), validate_logo_size],
        help_text="PNG with a transparent background works best. Shown about 40px tall. Up to 2 MB.",
    )
    show_name_with_logo = models.BooleanField(
        default=True,
        help_text="Untick if the logo already spells out “Diction Masters”, so the name isn't shown twice.",
    )
    favicon = models.ImageField(
        upload_to="branding/", blank=True,
        validators=[FileExtensionValidator(["png", "ico"]), validate_favicon_size],
        help_text="The small icon in the browser tab. A square PNG, at least 48×48 (512×512 is ideal), or an .ico file. Up to 500 KB.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "logo & favicon"
        verbose_name_plural = "logo & favicon"

    def __str__(self):
        return "Logo & favicon"

    def save(self, *args, **kwargs):
        self.pk = 1
        # Replacing or clearing a file removes the old one from storage.
        previous = SiteBranding.objects.filter(pk=1).first()
        super().save(*args, **kwargs)
        if previous:
            for name in ("logo", "favicon"):
                old, new = getattr(previous, name), getattr(self, name)
                if old and old.name != (new.name if new else ""):
                    old.storage.delete(old.name)

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)
