"""
Reading Club is Diction Masters' term-by-term book club — "this
term's reading book", read chapter by chapter, the same way it works
in the Student Modules pathway (Learning Modules), but one level
shallower: a chapter is opened straight from its term, without a
week or a day in between, since a chapter already *is* the lesson —
model reading audio, the chapter text, and any downloads.

A Book holds Terms (First, Second, Third...), each Term holds
numbered Chapters. Terms unlock in order, exactly like Learning
Modules — see apps.learning_modules.views for the shared pattern.
"""

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.book.models import AudioContent, VideoContent
from apps.learning_modules.models import COLOR_CHOICES, ICON_CHOICES


class Book(models.Model):
    """One book being read, e.g. "Things Fall Apart" this term."""

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    author = models.CharField(max_length=150, blank=True)
    description = models.CharField(
        max_length=255, blank=True, help_text="One or two sentences shown on the Reading Club hub."
    )
    overview = models.TextField(
        blank=True, help_text="A longer introduction shown on the book's own page."
    )
    icon = models.CharField(
        max_length=8, choices=ICON_CHOICES, default="📚", help_text="Shown on the book's badge."
    )
    color = models.CharField(
        max_length=7, choices=COLOR_CHOICES, default="#B8863B", help_text="Badge colour."
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(
        default=True, help_text="Unpublished books are hidden from the hub."
    )

    class Meta:
        ordering = ["order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "book"
            slug = base
            i = 1
            while Book.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Term(models.Model):
    """First / Second / Third term — however many a book needs.
    Terms unlock in order; see views._term_status."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=100, help_text='e.g. "First Term"')
    slug = models.SlugField(max_length=120, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("book", "slug")

    def __str__(self):
        return f"{self.book.title} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "term"
            slug = base
            i = 1
            while Term.objects.filter(book=self.book, slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Chapter(VideoContent, AudioContent):
    """One chapter — the model reading audio, the chapter text, and
    any downloads. This is the unit progress is tracked against."""

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="chapters")
    number = models.PositiveIntegerField(help_text="Chapter number within the term, e.g. 1")
    title = models.CharField(max_length=150, help_text='e.g. "The Beginning"')
    slug = models.SlugField(max_length=120, blank=True)
    summary = models.CharField(
        max_length=255, blank=True, help_text="One line shown in the term's list of chapters."
    )
    body = models.TextField(
        blank=True, help_text="The chapter text. Plain paragraphs — a blank line starts a new one."
    )
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]
        unique_together = ("term", "number")

    def __str__(self):
        return f"{self.term} — Chapter {self.number}: {self.title}"

    @property
    def display_name(self):
        return f"Chapter {self.number} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"chapter-{self.number}"
        super().save(*args, **kwargs)


class ChapterResource(models.Model):
    """A downloadable worksheet, PDF or external link attached to a chapter."""

    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="resources")
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="reading_club/resources/%Y/%m/", blank=True)
    url = models.URLField(blank=True, help_text="Use instead of a file upload for an externally hosted resource.")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def source(self):
        return self.url or (self.file.url if self.file else "")


class ChapterProgress(models.Model):
    """One row per (user, chapter) they've marked complete."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chapter_progress")
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="progress_entries")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "chapter")
        verbose_name_plural = "Chapter progress"

    def __str__(self):
        return f"{self.user} — {self.chapter}"
