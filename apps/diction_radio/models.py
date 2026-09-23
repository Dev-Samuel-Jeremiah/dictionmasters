from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.text import slugify


class RadioProgram(models.Model):
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    tagline = models.CharField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    presenter = models.CharField(max_length=120, blank=True)
    cover_image = models.ImageField(upload_to="diction_radio/programs/%Y/%m/", blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Sets when this programme plays in the station lineup.")
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "radio programme"
        verbose_name_plural = "radio programmes"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "programme"
            candidate = base
            index = 1
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                index += 1
                candidate = f"{base}-{index}"
            self.slug = candidate
        super().save(*args, **kwargs)


class RadioEpisode(models.Model):
    program = models.ForeignKey(RadioProgram, on_delete=models.CASCADE, related_name="episodes")
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)
    audio_file = models.FileField(
        upload_to="diction_radio/audio/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["mp3", "m4a", "aac", "wav", "ogg", "flac", "mp4"])],
        help_text="Upload an audio file, or provide a hosted audio link below.",
    )
    audio_url = models.URLField(blank=True, help_text="Use a hosted audio URL instead of uploading a file.")
    transcript = models.TextField(blank=True, help_text="Optional transcript for listeners who prefer to read along.")
    order = models.PositiveIntegerField(default=0, help_text="Playback order inside this programme.")
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["program__order", "program_id", "order", "id"]
        verbose_name = "radio episode"
        verbose_name_plural = "radio episodes"

    def __str__(self):
        return f"{self.program.title} — {self.title}"

    def clean(self):
        super().clean()
        if not self.audio_file and not self.audio_url:
            raise ValidationError({"audio_file": "Upload an audio file or add a hosted audio URL."})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "episode"
            candidate = base
            index = 1
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                index += 1
                candidate = f"{base}-{index}"
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def audio_source(self):
        return self.audio_url or (self.audio_file.url if self.audio_file else "")
