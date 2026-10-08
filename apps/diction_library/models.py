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
    # Which levels this is for, as ",Level 1,Level 2," — blank for every
    # level. Ticked in the control room; read by apps/accounts/access.py
    # (limit_to_level_list).
    levels = models.CharField(
        max_length=255, blank=True, default="",
        help_text="The levels this is for. Leave every box empty for every level.",
    )
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    # Read aloud (apps/diction_library/narration.py): the book's own
    # recording if one is uploaded, otherwise one made from its text, a
    # chapter at a time, with the words highlighted as they're read.
    narration_file = models.FileField(
        "Narration (optional)", upload_to="diction_library/narration/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["mp3", "m4a", "wav", "ogg"])],
        help_text="Your own recording of the book read aloud. Leave empty and one is made automatically "
                  "from the book's text, starting where the story starts (the contents pages are skipped).",
    )
    narration_redo = models.BooleanField(
        "Make the read-aloud again", default=False,
        help_text="Tick and save to make the read-aloud audio again from the current file (it uses voice credits).",
    )
    narration_status = models.CharField(max_length=12, blank=True, editable=False)
    narration_note = models.CharField(max_length=255, blank=True, editable=False)
    narration_chars = models.PositiveIntegerField(default=0, editable=False)
    narration_source = models.CharField(max_length=64, blank=True, editable=False)
    # Only one read-aloud works on a book at a time: whoever holds the claim,
    # which it keeps fresh as it goes (a crashed one's claim runs out).
    narration_owner = models.CharField(max_length=32, blank=True, editable=False)
    narration_updated = models.DateTimeField(null=True, blank=True, editable=False)

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

    @property
    def narration_label(self):
        return {
            "working": f"Being made — {self.narration_note}" if self.narration_note else "Being made",
            "ready": "Ready", "failed": f"Failed — {self.narration_note}", "off": self.narration_note or "Off",
        }.get(self.narration_status, "—")
    narration_label.fget.short_description = "Read-aloud"

    @property
    def ready_chapters(self):
        return [chapter for chapter in self.chapters.all() if chapter.audio_source]


class LibraryChapter(models.Model):
    """One chapter of a library book, read aloud: its words (the main text
    only — no contents pages) and the recording of them. Its word timings
    live in book.ReadAlongTiming like every other read-along."""

    item = models.ForeignKey(LibraryItem, on_delete=models.CASCADE, related_name="chapters")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True)
    text = models.TextField(help_text="The words read aloud, paragraphs separated by a blank line.")
    audio_file = models.FileField(upload_to="diction_library/narration/%Y/%m/", blank=True)
    audio_url = models.URLField(blank=True)
    # Made here from the text (its timings come with the voice), rather
    # than a recording someone uploaded (whose timings are measured).
    generated = models.BooleanField(default=False)
    source_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["item", "order"]
        constraints = [models.UniqueConstraint(fields=["item", "order"], name="one_chapter_per_place")]

    def __str__(self):
        return f"{self.item.title} — {self.title or f'Part {self.order + 1}'}"

    @property
    def audio_source(self):
        if self.audio_url:
            return self.audio_url
        try:
            return self.audio_file.url if self.audio_file else ""
        except ValueError:
            return ""

    @property
    def paragraphs(self):
        return [p for p in self.text.split("\n\n") if p.strip()]

    def read_along_self_timed(self):
        """Timings came with the voice: never measured over."""
        return self.generated


class LibraryRecording(models.Model):
    """One of a book's own narration recordings, e.g. "Chapter five" or
    "Page 121 to 124". A book can have many (uploaded together in the
    control room); each becomes a chapter of its read-aloud, put in order
    by the chapter or page in its name and matched to that part of the
    book's text (apps/diction_library/narration.py)."""

    item = models.ForeignKey(LibraryItem, on_delete=models.CASCADE, related_name="recordings")
    name = models.CharField(max_length=200, help_text='What it is, e.g. "Chapter five" or "Page 121 to 124".')
    audio_file = models.FileField(
        upload_to="diction_library/narration/%Y/%m/",
        validators=[FileExtensionValidator(["mp3", "m4a", "wav", "ogg", "aac"])],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item", "name"]

    def __str__(self):
        return self.name


def _recording_file_goes_too(sender, instance, **kwargs):
    """The recording's file leaves storage with it, unless a chapter row
    still points at it (it's tidied when the chapters are rebuilt)."""
    name = instance.audio_file.name if instance.audio_file else ""
    if name and not LibraryRecording.objects.filter(audio_file=name).exists():
        instance.audio_file.storage.delete(name)


models.signals.post_delete.connect(_recording_file_goes_too, sender=LibraryRecording,
                                   dispatch_uid="dm-library-recording-file")
