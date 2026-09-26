"""
Assembly Recitals: the pieces a school says or sings together at morning
assembly — the days of the week, the months of the year, numbers, diction
songs and anything else a school recites.

A Section (Days & Months, Numerals, Songs, Miscellaneous...) holds
Recitals. A Recital is one screen: its words, a line at a time, with a
model recording and/or a video to follow, and a Present mode for showing
it on a projector in the hall.
"""

from django.db import models
from django.utils.text import slugify

from apps.book.models import AudioContent, VideoContent


def _unique_slug(instance, text, queryset, fallback):
    base = slugify(text) or fallback
    slug, i = base, 1
    while queryset.filter(slug=slug).exclude(pk=instance.pk).exists():
        i += 1
        slug = f"{base}-{i}"
    return slug


class Section(models.Model):
    name = models.CharField(max_length=100, help_text='e.g. "Days & Months"')
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.CharField(max_length=255, blank=True, help_text="One line shown on the Assembly Recitals page.")
    icon = models.CharField(max_length=8, default="📣", help_text="An emoji for the section's card, e.g. 📅")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True, help_text="Unpublished sections are hidden from learners.")

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, self.name, Section.objects.all(), "section")
        super().save(*args, **kwargs)


class Recital(VideoContent, AudioContent):
    """One recital screen: the words, and a recording and/or video."""

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="recitals")
    title = models.CharField(max_length=150, help_text='e.g. "Days of the Week"')
    slug = models.SlugField(max_length=170, blank=True)
    summary = models.CharField(max_length=255, blank=True, help_text="One line shown in the section's list.")
    lines = models.TextField(
        blank=True,
        help_text="The words, one line per line, exactly as they are recited or sung. "
                  "Leave a blank line between verses.",
    )
    notes = models.TextField(blank=True, help_text="Optional notes for the teacher leading it, e.g. actions or how to split the hall.")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "title"]
        unique_together = ("section", "slug")

    def __str__(self):
        return f"{self.section.name} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, self.title, Recital.objects.filter(section_id=self.section_id), "recital")
        super().save(*args, **kwargs)

    @property
    def verses(self):
        """The words as verses, each a list of lines."""
        verses, current = [], []
        for raw in (self.lines or "").splitlines():
            line = raw.strip()
            if line:
                current.append(line)
            elif current:
                verses.append(current)
                current = []
        if current:
            verses.append(current)
        return verses

    @property
    def line_count(self):
        return sum(len(v) for v in self.verses)
