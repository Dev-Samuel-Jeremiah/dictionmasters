from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.text import slugify


class LibraryItem(models.Model):
    class Kind(models.TextChoices):
        BOOK = "book", "Book"
        STORY = "story", "Story"
        AUDIO = "audio", "Audio"
        VIDEO = "video", "Video"
        OTHER = "other", "Other resource"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.BOOK)
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True, help_text="Optional text or story content.")
    file = models.FileField(
        upload_to="diction_library/%Y/%m/",
        blank=True,
        validators=[FileExtensionValidator(["pdf", "epub", "doc", "docx", "txt", "mp3", "m4a", "wav", "ogg", "mp4", "webm", "mov", "jpg", "jpeg", "png", "webp"])],
        help_text="Books, documents, audio, video or cover image.",
    )
    external_url = models.URLField(blank=True, help_text="Optional link to hosted audio, video or a resource.")
    school = models.ForeignKey(
        "schools.School", null=True, blank=True, on_delete=models.CASCADE, related_name="library_items",
        help_text="Leave blank for content shared with every user. Select a school to limit access to its members.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="library_items"
    )
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "title"]
        verbose_name = "Diction Library item"
        verbose_name_plural = "Diction Library items"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "resource"
            candidate = base
            index = 1
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                index += 1
                candidate = f"{base}-{index}"
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def visibility_label(self):
        return self.school.name if self.school_id else "Everyone"
