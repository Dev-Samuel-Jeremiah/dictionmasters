"""
Lesson Notes to Audio: a teacher's lesson note, read aloud in a natural
British voice with every word highlighted as it is spoken, and the topic's
key words picked out for the teacher to hear and practise before the
lesson.

A note can be typed or pasted, uploaded (PDF, Word, text, or a photo of
the page) or written by the AI from a topic. The audio and the key words
are made in the background (apps/lesson_audio/services.py).
"""

import re

from django.conf import settings
from django.db import models
from django.urls import reverse

_MARKUP = re.compile(r"^\s*(?:#{1,6}\s+|[-*•▪●◦]\s+)")


def spoken_lines(body):
    """The note's lines as the voice reads them: one paragraph each (so a
    list item or heading gets its own pause), without markdown or bullet
    symbols, which would otherwise be read out or break the highlight."""
    lines = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        line = _MARKUP.sub("", line).replace("**", "").replace("__", "")
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return lines


_HEADING_END = re.compile(r"[.!?;,]$")


def is_heading(line):
    """A short line that isn't a sentence: "Behavioural Objectives",
    "Topic: Photosynthesis", "Step 2: Group work"."""
    return len(line) <= 70 and (line.endswith(":") or not _HEADING_END.search(line)) and len(line.split()) <= 9


def spoken_text(body):
    return "\n\n".join(spoken_lines(body))


class Job(models.TextChoices):
    """Where a background job (the audio, or the key words) stands."""
    NONE = "", "Not started"
    WORKING = "working", "Working"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class LessonNote(models.Model):
    SOURCE_CHOICES = [
        ("typed", "Typed or pasted"),
        ("upload", "Uploaded document"),
        ("photo", "Photo of a page"),
        ("ai", "Written with AI"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_notes")
    # The school the note belongs to (the owner's, when it was made): every
    # teacher there can find it, listen, practise and download it.
    # Blank for an individual's notes, which are theirs alone.
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, null=True, blank=True,
                               related_name="lesson_notes")
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=100, blank=True)
    class_level = models.CharField(max_length=100, blank=True, help_text='e.g. "Primary 4" or "JSS 2".')
    body = models.TextField(help_text="The note, paragraphs separated by a blank line.")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="typed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # The read-aloud. audio_text is exactly what the voice read (the body
    # as it was then), so the highlight stays right even after the note is
    # edited; the page then offers to make the audio again.
    audio_file = models.FileField(upload_to="lesson_audio/%Y/%m/", blank=True)
    audio_text = models.TextField(blank=True)
    audio_voice = models.CharField(max_length=40, blank=True)
    audio_duration = models.FloatField(null=True, blank=True)
    audio_status = models.CharField(max_length=10, choices=Job.choices, default=Job.NONE, blank=True)
    audio_error = models.CharField(max_length=300, blank=True)
    audio_updated = models.DateTimeField(null=True, blank=True)

    keywords_status = models.CharField(max_length=10, choices=Job.choices, default=Job.NONE, blank=True)
    keywords_error = models.CharField(max_length=300, blank=True)
    keywords_text = models.TextField(blank=True, help_text="The body the key words were picked from.")
    keywords_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("lesson_audio:note", args=[self.pk])

    @property
    def paragraphs(self):
        return [p.strip() for p in self.body.split("\n\n") if p.strip()]

    @property
    def audio_blocks(self):
        """What the voice read, for the read-along: (kind, text) with
        headings marked, so the page can show them as headings."""
        return [("h" if is_heading(p) else "p", p) for p in self.audio_text.split("\n\n") if p.strip()]

    @property
    def audio_source(self):
        try:
            return self.audio_file.url if self.audio_file else ""
        except ValueError:
            return ""

    @property
    def audio_url(self):
        # read_along looks for an audio_url beside audio_file.
        return ""

    @property
    def audio_is_current(self):
        return bool(self.audio_file) and self.audio_text == spoken_text(self.body)

    @property
    def keywords_are_current(self):
        return self.keywords_text.strip() == self.body.strip()

    @property
    def word_count(self):
        return len(self.body.split())

    @property
    def minutes(self):
        """About how long the note takes to read aloud (150 words a minute)."""
        return max(1, round(self.word_count / 150))

    def read_along_self_timed(self):
        """Its timings come with the voice: never measured over."""
        return True

    # The protected player (apps/videos) plays any row with a video_file
    # and keeps it offline inside the app; here that's the read-aloud. The
    # MP3 itself is never offered as a download.
    @property
    def video_file(self):
        return self.audio_file if self.audio_file else None

    @property
    def video_source(self):
        return "audio" if self.audio_file else ""

    @property
    def video_caption(self):
        return f"Lesson note: {self.title}"


class KeyWord(models.Model):
    note = models.ForeignKey(LessonNote, on_delete=models.CASCADE, related_name="keywords")
    order = models.PositiveIntegerField(default=0)
    word = models.CharField(max_length=80)
    meaning = models.CharField(max_length=300, blank=True)
    ipa = models.CharField(max_length=120, blank=True)
    # How it breaks into syllables, the stressed one in capitals:
    # "pho·to·SYN·the·sis".
    syllables = models.CharField(max_length=120, blank=True)
    tip = models.CharField(max_length=300, blank=True, help_text="What to listen for when saying it.")
    audio_file = models.FileField(upload_to="lesson_audio/words/%Y/%m/", blank=True)
    added_by_teacher = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)
    mastered = models.BooleanField(default=False)
    last_heard = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.word

    @property
    def audio_source(self):
        try:
            return self.audio_file.url if self.audio_file else ""
        except ValueError:
            return ""


class Usage(models.Model):
    """What each person has asked the paid services for, for fair daily limits."""
    KIND_CHOICES = [("audio", "Audio characters"), ("write", "AI lesson notes"), ("words", "Key word sets"),
                    ("practice", "Practice attempts"), ("read", "Pages read from photos")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    amount = models.PositiveIntegerField(default=1)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "kind", "at"])]
