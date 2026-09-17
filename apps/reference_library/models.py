"""
The Reference Library is Diction Masters' second Learning Tool — a
place to look things up rather than follow a lesson: grammar points,
spelling rules, word origins, style notes, anything a curious child
(or their teacher) might want to research.

Everything here is meant to be filled in from the Django admin: a
LibraryCategory groups LibraryArticles, each article can carry any
number of LibraryTags (for cross-topic search) and LibraryAttachments
(a downloadable worksheet or reference sheet).
"""

from django.db import models
from django.utils.text import slugify


class LibraryCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.CharField(
        max_length=255, blank=True, help_text="One line shown under the category name."
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Library categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "category"
            slug = base
            i = 1
            while LibraryCategory.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def published_article_count(self):
        return self.articles.filter(is_published=True).count()


class LibraryTag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class LibraryArticle(models.Model):
    category = models.ForeignKey(LibraryCategory, on_delete=models.CASCADE, related_name="articles")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    summary = models.CharField(
        max_length=300,
        blank=True,
        help_text="One or two sentences shown in search results and listings.",
    )
    body = models.TextField(help_text="The full article. Plain paragraphs — a blank line starts a new one.")
    tags = models.ManyToManyField(LibraryTag, blank=True, related_name="articles")
    source_credit = models.CharField(
        max_length=255, blank=True, help_text='e.g. "Adapted from the Oxford Guide to English Grammar"'
    )
    external_link = models.URLField(blank=True, help_text="Optional — a place to read further.")
    is_published = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__order", "order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "article"
            slug = base
            i = 1
            while LibraryArticle.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class LibraryAttachment(models.Model):
    article = models.ForeignKey(LibraryArticle, on_delete=models.CASCADE, related_name="attachments")
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="library/attachments/%Y/%m/", blank=True)
    url = models.URLField(blank=True, help_text="Use instead of a file upload for an externally hosted document.")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def source(self):
        return self.url or (self.file.url if self.file else "")
