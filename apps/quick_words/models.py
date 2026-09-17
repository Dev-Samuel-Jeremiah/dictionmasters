"""
Quick Words — the word library.

A flat, searchable dictionary of words a learner can look up in
seconds: how it sounds, what it means, how it is used. Unlike EchoSpell
(where words live inside a level's group and are worked through in
order) a QuickWord belongs to nobody — it is reference material, tagged
with the level it suits so a teacher can judge whether it fits a class.

On top of that sits WordList: a teacher or learner's own saved
selection, e.g. "Class 6A Spelling", built by adding words as they
browse.
"""

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.book.models import AudioContent
from apps.echospell.models import LEVEL_NAME_CHOICES


class QuickWord(AudioContent):
    """One word in the library."""

    SOURCE_STAFF = "staff"
    SOURCE_AI = "ai"
    SOURCE_CHOICES = [
        (SOURCE_STAFF, "Added by staff"),
        (SOURCE_AI, "Looked up by AI"),
    ]

    word = models.CharField(max_length=100)
    # AI entries go straight into the shared library, so staff need to be
    # able to find and check them.
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_STAFF)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    ipa = models.CharField(
        max_length=100, blank=True, verbose_name="transcription",
        help_text='Phonemic transcription, e.g. "/əˈtʃiːv/"',
    )
    definition = models.TextField(help_text="One clear sentence a child can understand.")
    example_sentence = models.TextField(
        blank=True, help_text="The word used in a full sentence.",
    )
    level = models.CharField(
        max_length=100, choices=LEVEL_NAME_CHOICES, blank=True,
        help_text="The level this word suits. Optional.",
    )
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["word"]

    def __str__(self):
        return self.word

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.word) or "word"
            slug = base
            i = 1
            while QuickWord.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class WordList(models.Model):
    """A saved selection of words, owned by whoever built it."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="word_lists"
    )
    name = models.CharField(max_length=120)
    words = models.ManyToManyField(QuickWord, blank=True, related_name="lists")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("user", "name")

    def __str__(self):
        return self.name
