"""
The Book of Conversation is Diction Masters' first Learning Tool.
Inside it, the 44 Academy is one lesson per sound of English: a
child taps a sound on the chart and lands on a page with several
tabs — Lens (articulation), Word Bank, Sentence Practice, Passage,
Conversations, Twisters, Minimal Pairs, and External Links.

Everything here is meant to be filled in from the Django admin —
a SoundCategory holds Sounds, and a Sound holds one Articulation
(its "Lens" tab) plus any number of entries in each other tab, so a
teacher building the library never touches code, only the admin.

Media (video/audio) can either be uploaded straight into the admin
(stored under MEDIA_ROOT) or pasted in as a URL — useful once the
video library is served from Cloudflare R2 instead. Whichever is
filled in wins; see the `*_source` properties.
"""

from django.db import models
from django.utils.text import slugify


class VideoContent(models.Model):
    """Reusable video fields: an upload, or a URL, for CDN-hosted video."""

    video_file = models.FileField(upload_to="book/videos/%Y/%m/", blank=True)
    video_url = models.URLField(
        blank=True,
        help_text="Use instead of a file upload for CDN-hosted video (e.g. Cloudflare R2, YouTube).",
    )
    video_caption = models.CharField(max_length=150, blank=True)
    video_duration_label = models.CharField(
        max_length=30, blank=True, help_text='e.g. "2-3 min"'
    )
    video_poster = models.ImageField(
        upload_to="posters/%Y/%m/",
        blank=True,
        help_text="The still shown before the video plays. Taken from the video "
                  "automatically; upload your own to replace it.",
    )

    class Meta:
        abstract = True

    @property
    def video_source(self):
        return self.video_url or (self.video_file.url if self.video_file else "")

    @property
    def poster_source(self):
        """The still to show before play, so a video never opens black."""
        return self.video_poster.url if self.video_poster else ""


class AudioContent(models.Model):
    """Reusable audio fields: an upload, or a URL."""

    audio_file = models.FileField(upload_to="book/audio/%Y/%m/", blank=True)
    audio_url = models.URLField(
        blank=True,
        help_text="Use instead of a file upload for CDN-hosted audio.",
    )

    class Meta:
        abstract = True

    @property
    def audio_source(self):
        return self.audio_url or (self.audio_file.url if self.audio_file else "")


class OrderedForSound(models.Model):
    order = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["order", "id"]


# ---------------------------------------------------------------------------
# The 44 Academy: categories and sounds
# ---------------------------------------------------------------------------

class SoundCategory(models.Model):
    """e.g. Long Vowels, Short Vowels, Diphthongs, Consonants."""

    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "Sound categories"

    def __str__(self):
        return self.name


class Sound(models.Model):
    """One of the 44 sounds of English, and the home of its lesson page."""

    category = models.ForeignKey(SoundCategory, on_delete=models.CASCADE, related_name="sounds")
    symbol = models.CharField(max_length=20, help_text='e.g. "/i\u02d0/"')
    name = models.CharField(max_length=100, help_text='e.g. "Long EE"')
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    example_words = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated, e.g. seat, feel, sheep, clean, dream, reach, teach",
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(
        default=True,
        help_text="Unpublished sounds are hidden from the 44 Academy grid.",
    )

    class Meta:
        ordering = ["category__order", "order", "name"]

    def __str__(self):
        return f"{self.symbol} {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or slugify(self.symbol) or "sound"
            slug = base
            i = 1
            while Sound.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def example_word_list(self):
        return [w.strip() for w in self.example_words.split(",") if w.strip()]


# ---------------------------------------------------------------------------
# Lens tab — articulation (one per sound)
# ---------------------------------------------------------------------------

class Articulation(VideoContent):
    sound = models.OneToOneField(Sound, on_delete=models.CASCADE, related_name="articulation")
    trap_heading = models.CharField(max_length=100, default="The Nigerian Trap")
    trap_text = models.TextField(
        blank=True, help_text="The common mistake Nigerian learners make with this sound."
    )
    mouth_position_text = models.TextField(
        blank=True, help_text="How to shape the mouth, lips and tongue for this sound."
    )
    practice_words = models.CharField(
        max_length=255,
        blank=True,
        help_text="Short list shown on the lesson page, e.g. seat, feel, sheep",
    )
    qr_code = models.CharField(max_length=30, blank=True, editable=False)
    qr_label = models.CharField(max_length=150, blank=True, editable=False)

    class Meta:
        verbose_name = "Articulation (Lens tab)"
        verbose_name_plural = "Articulation (Lens tab)"

    def __str__(self):
        return f"Articulation — {self.sound}"

    def save(self, *args, **kwargs):
        if not self.qr_code and self.sound_id:
            self.qr_code = f"DM-BOC-{self.sound_id}"
        if not self.qr_label and self.sound_id:
            self.qr_label = f"QR Code \u2014 Sound {self.sound.order} \u2014 {self.sound.symbol} {self.sound.name}"
        super().save(*args, **kwargs)

    @property
    def practice_word_list(self):
        return [w.strip() for w in self.practice_words.split(",") if w.strip()]


# ---------------------------------------------------------------------------
# Word Bank tab
# ---------------------------------------------------------------------------

class WordBankEntry(AudioContent, OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="word_bank_entries")
    word = models.CharField(max_length=100)
    spelling_pattern = models.TextField(
        blank=True, help_text='e.g. "ee, ea and ey can all spell this sound."'
    )

    class Meta(OrderedForSound.Meta):
        abstract = False
        verbose_name_plural = "Word bank entries"

    def __str__(self):
        return self.word


# ---------------------------------------------------------------------------
# Sentence Practice tab
# ---------------------------------------------------------------------------

class SentencePractice(AudioContent, OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="sentence_practices")
    sentence = models.TextField()

    class Meta(OrderedForSound.Meta):
        abstract = False
        verbose_name_plural = "Sentence practice"

    def __str__(self):
        return self.sentence[:60]


# ---------------------------------------------------------------------------
# Passage tab
# ---------------------------------------------------------------------------

class Passage(AudioContent, OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="passages")
    title = models.CharField(max_length=150)
    body = models.TextField()

    class Meta(OrderedForSound.Meta):
        abstract = False

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Conversations tab (dialogue)
# ---------------------------------------------------------------------------

class Conversation(AudioContent, OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=150)
    script = models.TextField(help_text="One line per turn, e.g. \"A: Good morning!\"")

    class Meta(OrderedForSound.Meta):
        abstract = False

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Twisters tab
# ---------------------------------------------------------------------------

class TongueTwister(AudioContent, OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="tongue_twisters")
    text = models.TextField()

    class Meta(OrderedForSound.Meta):
        abstract = False
        verbose_name = "Tongue twister"

    def __str__(self):
        return self.text[:60]


# ---------------------------------------------------------------------------
# Minimal Pairs tab — one audio file for the whole tab, not per pair
# ---------------------------------------------------------------------------

class MinimalPairsAudio(AudioContent):
    """The single audio recording that covers every minimal pair listed
    for this sound (e.g. "sheep vs ship, beach vs bitch, ..." read as
    one track) — one per sound, not one per pair."""

    sound = models.OneToOneField(Sound, on_delete=models.CASCADE, related_name="minimal_pairs_audio")

    class Meta:
        verbose_name = "Minimal pairs audio (one per sound)"
        verbose_name_plural = "Minimal pairs audio (one per sound)"

    def __str__(self):
        return f"Minimal pairs audio — {self.sound}"


class MinimalPair(OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="minimal_pairs")
    word_a = models.CharField(max_length=100)
    word_b = models.CharField(max_length=100)
    notes = models.TextField(blank=True, help_text="What makes these two easy to confuse.")

    class Meta(OrderedForSound.Meta):
        abstract = False
        verbose_name_plural = "Minimal pairs"

    def __str__(self):
        return f"{self.word_a} / {self.word_b}"


# ---------------------------------------------------------------------------
# External Links tab (text only)
# ---------------------------------------------------------------------------

class ExternalLink(OrderedForSound):
    sound = models.ForeignKey(Sound, on_delete=models.CASCADE, related_name="external_links")
    title = models.CharField(max_length=150)
    url = models.URLField()
    description = models.TextField(blank=True)

    class Meta(OrderedForSound.Meta):
        abstract = False

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Phonemic chart audio (one recording per chart sound)
# ---------------------------------------------------------------------------

class PhonemeAudio(AudioContent):
    """The spoken keyword for one sound on the phonemic chart.

    Made automatically with ElevenLabs the first time the chart needs it
    (see phoneme_audio.py), or uploaded by an admin, which then takes the
    place of the generated one. `key` is the chart's own name for the
    sound ("fleece", "think"), so a recording belongs to the chart even
    before a 44 Academy lesson exists for that sound.
    """

    SOURCE_GENERATED = "generated"
    SOURCE_UPLOADED = "uploaded"
    SOURCE_CHOICES = [(SOURCE_GENERATED, "Generated with ElevenLabs"), (SOURCE_UPLOADED, "Uploaded by an admin")]

    key = models.SlugField(max_length=40, unique=True, help_text='The chart keyword, e.g. "fleece".')
    symbol = models.CharField(max_length=10)
    spoken_text = models.CharField(max_length=255, blank=True, help_text="What the recording says.")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_GENERATED)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        verbose_name = "Phonemic chart audio"
        verbose_name_plural = "Phonemic chart audio"

    def __str__(self):
        return f"/{self.symbol}/ {self.key}"


# ---------------------------------------------------------------------------
# Read along: when each word is really spoken in a recording
# ---------------------------------------------------------------------------

class ReadAlongTiming(models.Model):
    """The measured start and end of every word in one recording, so the
    read-along highlight follows the voice rather than an estimate.

    Made in the background by apps.book.read_along and kept for any
    passage, dialogue, lesson or chapter that has text beside its audio
    or video. The fingerprint is the recording plus the text: change
    either and the timing is measured again."""

    STATUS_WORKING = "working"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_WORKING, "Working"), (STATUS_READY, "Ready"), (STATUS_FAILED, "Failed")]

    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_WORKING)
    engine = models.CharField(max_length=20, blank=True)
    words = models.JSONField(default=list, blank=True, help_text="[[word, start, end], …] in seconds.")
    error = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("content_type", "object_id")
        verbose_name = "read-along timing"

    def __str__(self):
        return f"{self.content_type.model} {self.object_id} — {self.get_status_display()}"
