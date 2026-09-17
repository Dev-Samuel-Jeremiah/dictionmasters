from concurrent.futures import ThreadPoolExecutor

from django.contrib import admin, messages
from django.core.files.base import ContentFile

from apps.book.media_status import media_pills

from .models import QuickWord, WordList
from .speech import SpeechUnavailable, is_configured as speech_is_configured, synthesise

# Audio for this many words per click. At ~1.5s each, spoken four at a
# time, that keeps one admin request comfortably short.
AUDIO_BATCH = 40


def _speak_or_none(word):
    try:
        return synthesise(word.word)
    except SpeechUnavailable:
        return None


@admin.register(QuickWord)
class QuickWordAdmin(admin.ModelAdmin):
    list_display = ["word", "ipa", "level", "source", "media_status", "list_count", "is_published"]
    list_filter = ["source", "level", "is_published"]
    search_fields = ["word", "definition", "example_sentence", "ipa"]
    prepopulated_fields = {"slug": ("word",)}
    ordering = ["word"]
    fieldsets = [
        (None, {"fields": ["word", "slug", "level", "source", "is_published"]}),
        ("Pronunciation", {"fields": ["ipa", ("audio_file", "audio_url")]}),
        ("Meaning", {"fields": ["definition", "example_sentence"]}),
    ]

    actions = ["generate_pronunciation"]

    def list_count(self, obj):
        return obj.lists.count()
    list_count.short_description = "In lists"

    # Not called "media": ModelAdmin.media is Django's own page assets.
    @admin.display(description="Media")
    def media_status(self, obj):
        return media_pills(obj)

    @admin.action(description="Generate pronunciation audio for selected words that have none")
    def generate_pronunciation(self, request, queryset):
        if not speech_is_configured():
            self.message_user(request, "ElevenLabs isn't configured — add the key and voice to .env.", messages.ERROR)
            return

        # Never replace audio someone already added — only fill the gaps.
        needing_audio = queryset.filter(audio_file="", audio_url="")
        total_needing = needing_audio.count()
        skipped = queryset.count() - total_needing
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} word{'s' if skipped != 1 else ''} that already have audio.",
                messages.INFO,
            )

        words = list(needing_audio[:AUDIO_BATCH])
        if not words:
            return
        with ThreadPoolExecutor(max_workers=4) as pool:
            recordings = list(pool.map(_speak_or_none, words))

        saved = 0
        for word, audio in zip(words, recordings):
            if audio is None:
                continue
            word.audio_file.save(f"{word.slug}.mp3", ContentFile(audio), save=True)
            saved += 1

        failed = len(words) - saved
        self.message_user(request, f"Pronunciation saved for {saved} word{'s' if saved != 1 else ''}.", messages.SUCCESS)
        if failed:
            self.message_user(request, f"{failed} couldn't be generated — try those again shortly.", messages.WARNING)
        if total_needing > AUDIO_BATCH:
            self.message_user(request, f"Only the first {AUDIO_BATCH} were done; select the rest and run it again.", messages.INFO)


@admin.register(WordList)
class WordListAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "word_count", "created_at"]
    search_fields = ["name", "user__email"]
    filter_horizontal = ["words"]
    readonly_fields = ["created_at"]

    def word_count(self, obj):
        return obj.words.count()
    word_count.short_description = "Words"
