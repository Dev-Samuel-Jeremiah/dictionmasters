"""
Learning Modules — structured, term-by-term courses (Diction Masters'
own "Student Modules" pathway: Sound Discovery, Book Club, Public
Speaking, Diction Recital, and any others added from the admin).

The shape mirrors the Nigerian school year: a LearningModule holds
Terms (First, Second, Third...), each Term holds Weeks, and each Week
holds up to five Days (Monday-Friday). A Day is not itself a lesson —
it holds an ordered list of LessonItems (a short video, an audio
track, or both, each with its own title), the same way a school day
covers a few short activities rather than one long one.

Progress is tracked per Day (DayProgress), earned by opening every one
of the day's lesson items (DayItemsSeen; see lesson_path.py). Terms and
Weeks unlock in order: a Term/Week stays locked until the one before it is complete,
computed live from DayProgress rather than stored — see
views._term_status / _week_status.
"""

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify

from apps.book.models import AudioContent, VideoContent

# Curated so the admin's Icon field is a dropdown rather than free-typed
# emoji — easy to pick from, and guarantees it renders consistently.
ICON_CHOICES = [
    ("📚", "📚 Books"),
    ("📖", "📖 Open book"),
    ("🔍", "🔍 Magnifying glass"),
    ("🎤", "🎤 Microphone"),
    ("🎧", "🎧 Headphones"),
    ("🗣️", "🗣️ Speaking head"),
    ("💬", "💬 Speech bubble"),
    ("✍️", "✍️ Writing hand"),
    ("📝", "📝 Notes"),
    ("🔤", "🔤 Letters"),
    ("🧠", "🧠 Brain"),
    ("🎯", "🎯 Target"),
    ("🎭", "🎭 Theatre masks"),
    ("🎨", "🎨 Palette"),
    ("🎵", "🎵 Musical note"),
    ("🧩", "🧩 Puzzle piece"),
    ("🔬", "🔬 Microscope"),
    ("🧭", "🧭 Compass"),
    ("🧮", "🧮 Abacus"),
    ("🗓️", "🗓️ Calendar"),
    ("⭐", "⭐ Star"),
    ("🌟", "🌟 Glowing star"),
    ("🏆", "🏆 Trophy"),
    ("🏅", "🏅 Medal"),
    ("🎓", "🎓 Graduation cap"),
    ("📣", "📣 Megaphone"),
    ("🚀", "🚀 Rocket"),
    ("🌍", "🌍 Globe"),
]

# Same idea for Color — a curated palette dropdown instead of a raw hex
# field, mixing the site's own notebook palette with a few extra hues
# so modules can be told apart at a glance.
COLOR_CHOICES = [
    ("#14213D", "Ink navy"),
    ("#7A2438", "Maroon"),
    ("#B8863B", "Gold"),
    ("#24473E", "Green"),
    ("#0B5E5E", "Teal"),
    ("#1F6F8B", "Ocean blue"),
    ("#7C3AED", "Purple"),
    ("#8E44AD", "Violet"),
    ("#9D174D", "Rose"),
    ("#B03A2E", "Rust"),
    ("#C2410C", "Amber"),
    ("#374151", "Slate"),
]


class LearningModule(models.Model):
    """A course on the term-by-term pathway, e.g. "Sound Discovery"."""

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.CharField(
        max_length=255, blank=True, help_text="One or two sentences shown on the Learning Modules hub."
    )
    overview = models.TextField(
        blank=True, help_text="A longer introduction shown on the module's own page."
    )
    icon = models.CharField(
        max_length=8, choices=ICON_CHOICES, default="📚", help_text="Shown on the module's badge."
    )
    color = models.CharField(
        max_length=7, choices=COLOR_CHOICES, default="#14213D", help_text="Badge colour."
    )
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(
        default=True, help_text="Unpublished modules are hidden from the hub."
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "module"
            slug = base
            i = 1
            while LearningModule.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Term(models.Model):
    """First / Second / Third term — however many a module needs.
    Terms unlock in order; see views._term_status."""

    module = models.ForeignKey(LearningModule, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=100, help_text='e.g. "First Term"')
    slug = models.SlugField(max_length=120, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("module", "slug")

    def __str__(self):
        return f"{self.module.name} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "term"
            slug = base
            i = 1
            while Term.objects.filter(module=self.module, slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class Week(models.Model):
    """One numbered week inside a term. Weeks unlock in order within
    their term; see views._week_status."""

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="weeks")
    number = models.PositiveIntegerField(help_text="Week number within the term, e.g. 1")
    title = models.CharField(max_length=150, blank=True, help_text='Optional, e.g. "Revision Week"')
    slug = models.SlugField(max_length=120, blank=True)

    class Meta:
        ordering = ["number"]
        unique_together = ("term", "number")

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return f"Week {self.number}" + (f" — {self.title}" if self.title else "")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"week-{self.number}"
        super().save(*args, **kwargs)


DAY_CHOICES = [
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
]
DAY_ORDER = [key for key, _label in DAY_CHOICES]


class Day(models.Model):
    """One school day within a week — a short playlist of LessonItems,
    not a lesson itself. Completion (DayProgress) is tracked here."""

    week = models.ForeignKey(Week, on_delete=models.CASCADE, related_name="days")
    day_name = models.CharField(max_length=10, choices=DAY_CHOICES)
    order = models.PositiveIntegerField(default=0, editable=False)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("week", "day_name")

    def __str__(self):
        return f"{self.get_day_name_display()} — {self.week}"

    def save(self, *args, **kwargs):
        self.order = DAY_ORDER.index(self.day_name) if self.day_name in DAY_ORDER else 0
        super().save(*args, **kwargs)


class LessonItem(VideoContent, AudioContent):
    """One activity within a day — a short video, an audio track, or
    both, plus optional notes and downloadable resources."""

    day = models.ForeignKey(Day, on_delete=models.CASCADE, related_name="lesson_items")
    title = models.CharField(max_length=150, help_text='e.g. "Sound Introduction"')
    description = models.CharField(
        max_length=255, blank=True, help_text="One line shown under the title, e.g. what this activity covers."
    )
    body = models.TextField(blank=True, help_text="Optional notes or a transcript shown below the player.")
    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def kind(self):
        has_video = bool(self.video_source)
        has_audio = bool(self.audio_source)
        if has_video and has_audio:
            return "both"
        if has_video:
            return "video"
        if has_audio:
            return "audio"
        if self.pk and self.slides.exists():
            return "slides"
        return "text"


class LessonSlide(models.Model):
    """One picture in a lesson item's photo slideshow, for children to
    page through: a big picture, an optional caption, and optionally a
    recording that plays as the slide opens. Added many at a time from
    the control room (apps/manage/slides.py)."""

    lesson_item = models.ForeignKey(LessonItem, on_delete=models.CASCADE, related_name="slides")
    image = models.ImageField(upload_to="learning_modules/slides/%Y/%m/")
    caption = models.CharField(max_length=200, blank=True, help_text='Shown under the picture, e.g. "A big red apple".')
    audio_file = models.FileField(
        upload_to="learning_modules/slides/audio/%Y/%m/", blank=True,
        help_text="Optional: a recording that plays when this slide opens, e.g. the word being said.",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.caption or f"Slide {self.order + 1}"


@receiver(post_delete, sender=LessonSlide)
def _slide_files_go_too(sender, instance, **kwargs):
    """A slide's picture and sound leave storage with it — also when the
    whole lesson item, day or module it belongs to is deleted."""
    for field in (instance.image, instance.audio_file):
        if field:
            field.storage.delete(field.name)


class LessonResource(models.Model):
    """A downloadable worksheet, PDF or external link attached to a lesson item."""

    lesson_item = models.ForeignKey(LessonItem, on_delete=models.CASCADE, related_name="resources")
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="learning_modules/resources/%Y/%m/", blank=True)
    url = models.URLField(blank=True, help_text="Use instead of a file upload for an externally hosted resource.")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def source(self):
        return self.url or (self.file.url if self.file else "")


class DayProgress(models.Model):
    """One row per (user, day) they've marked complete. Terms and
    weeks unlock in order based on whether every Day in the previous
    one has a DayProgress row for the current user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="day_progress")
    day = models.ForeignKey(Day, on_delete=models.CASCADE, related_name="progress_entries")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "day")
        verbose_name_plural = "Day progress"

    def __str__(self):
        return f"{self.user} — {self.day}"


class DayItemsSeen(models.Model):
    """Which lesson items of a day a learner has opened, one screen at a
    time (apps/learning_modules/lesson_path.py). The day is earned —
    DayProgress written — once every published item has been opened."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="day_items_seen")
    day = models.ForeignKey(Day, on_delete=models.CASCADE, related_name="+")
    items_seen = models.JSONField(default=list, blank=True, help_text="LessonItem ids opened, in the order first opened.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day"], name="one_items_seen_per_day")]
        verbose_name = "day items seen"
        verbose_name_plural = "day items seen"

    def __str__(self):
        return f"{self.user} — {self.day}"
