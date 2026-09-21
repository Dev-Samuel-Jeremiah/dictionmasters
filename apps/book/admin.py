from django.contrib import admin

from .models import (
    Articulation,
    Conversation,
    ExternalLink,
    MinimalPair,
    MinimalPairsAudio,
    PhonemeAudio,
    Passage,
    SectionVideo,
    SentencePractice,
    Sound,
    SoundCategory,
    TongueTwister,
    WordBankEntry,
)


@admin.register(SoundCategory)
class SoundCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "sound_count"]
    ordering = ["order"]

    def sound_count(self, obj):
        return obj.sounds.count()
    sound_count.short_description = "Sounds"


class ArticulationInline(admin.StackedInline):
    model = Articulation
    extra = 1
    max_num = 1
    can_delete = False
    fields = [
        ("video_file", "video_url"),
        ("video_caption", "video_duration_label"),
        "video_poster",
        ("trap_heading", "trap_text"),
        "mouth_position_text",
        "practice_words",
    ]


class WordBankEntryInline(admin.TabularInline):
    model = WordBankEntry
    extra = 1
    fields = ["order", "word", "spelling_pattern", "audio_file", "audio_url"]


class SentencePracticeInline(admin.TabularInline):
    model = SentencePractice
    extra = 1
    fields = ["order", "sentence", "audio_file", "audio_url"]


class PassageInline(admin.StackedInline):
    model = Passage
    extra = 0
    fields = ["order", "title", "body", "audio_file", "audio_url"]


class ConversationInline(admin.StackedInline):
    model = Conversation
    extra = 0
    fields = ["order", "title", "script", "audio_file", "audio_url"]


class TongueTwisterInline(admin.TabularInline):
    model = TongueTwister
    extra = 1
    fields = ["order", "text", "audio_file", "audio_url"]


class MinimalPairsAudioInline(admin.StackedInline):
    model = MinimalPairsAudio
    extra = 1
    max_num = 1
    can_delete = False
    verbose_name = "Minimal pairs audio (one recording for the whole tab)"
    fields = [("audio_file", "audio_url")]


class MinimalPairInline(admin.TabularInline):
    model = MinimalPair
    extra = 1
    fields = ["order", "word_a", "word_b", "notes"]


class ExternalLinkInline(admin.TabularInline):
    model = ExternalLink
    extra = 1
    fields = ["order", "title", "url", "description"]


class SectionVideoInline(admin.StackedInline):
    """Videos for any tab of the lesson — as many per tab as needed."""
    model = SectionVideo
    extra = 0
    fields = [("section", "order"), "video_caption", ("video_file", "video_url"),
              "video_duration_label", "video_poster"]
    verbose_name = "video"
    verbose_name_plural = "Videos on the lesson's tabs (Lens, Word Bank, Passage …)"


@admin.register(SectionVideo)
class SectionVideoAdmin(admin.ModelAdmin):
    list_display = ["__str__", "sound", "section", "order"]
    list_filter = ["section", "sound__category"]
    search_fields = ["video_caption", "sound__name", "sound__symbol"]
    ordering = ["sound", "section", "order"]


@admin.register(Sound)
class SoundAdmin(admin.ModelAdmin):
    list_display = ["symbol", "name", "category", "order", "is_published"]
    list_filter = ["category", "is_published"]
    search_fields = ["name", "symbol", "example_words"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["category__order", "order"]
    inlines = [
        ArticulationInline,
        SectionVideoInline,
        WordBankEntryInline,
        SentencePracticeInline,
        PassageInline,
        ConversationInline,
        TongueTwisterInline,
        MinimalPairsAudioInline,
        MinimalPairInline,
        ExternalLinkInline,
    ]
    fieldsets = [
        (None, {
            "fields": ["category", "symbol", "name", "slug", "example_words", "order", "is_published"],
        }),
    ]


# Standalone registrations too, so content can be found and edited
# by searching across every sound, not only from inside one Sound.

@admin.register(WordBankEntry)
class WordBankEntryAdmin(admin.ModelAdmin):
    list_display = ["word", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["word", "sound__name"]


@admin.register(SentencePractice)
class SentencePracticeAdmin(admin.ModelAdmin):
    list_display = ["sentence", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["sentence", "sound__name"]


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    list_display = ["title", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["title", "body", "sound__name"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["title", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["title", "script", "sound__name"]


@admin.register(TongueTwister)
class TongueTwisterAdmin(admin.ModelAdmin):
    list_display = ["text", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["text", "sound__name"]


@admin.register(MinimalPair)
class MinimalPairAdmin(admin.ModelAdmin):
    list_display = ["word_a", "word_b", "sound", "order"]
    list_filter = ["sound__category"]
    search_fields = ["word_a", "word_b", "sound__name"]


@admin.register(ExternalLink)
class ExternalLinkAdmin(admin.ModelAdmin):
    list_display = ["title", "sound", "url", "order"]
    list_filter = ["sound__category"]
    search_fields = ["title", "sound__name"]


@admin.register(PhonemeAudio)
class PhonemeAudioAdmin(admin.ModelAdmin):
    """The spoken keyword for each phonemic chart sound. Made
    automatically; upload a teacher's recording to replace one."""

    list_display = ["key", "symbol_display", "has_recording", "source", "spoken_text", "updated_at"]
    list_filter = ["source"]
    search_fields = ["key", "symbol", "spoken_text"]
    readonly_fields = ["spoken_text", "updated_at"]
    fields = ["key", "symbol", ("audio_file", "audio_url"), "source", "spoken_text", "updated_at"]
    actions = ["regenerate", "generate_missing"]

    @admin.display(description="Sound")
    def symbol_display(self, obj):
        return f"/{obj.symbol}/"

    @admin.display(boolean=True, description="Audio")
    def has_recording(self, obj):
        return bool(obj.audio_file or obj.audio_url)

    def save_model(self, request, obj, form, change):
        # A file or link chosen here is a teacher's recording: keep it.
        if "audio_file" in form.changed_data or "audio_url" in form.changed_data:
            obj.source = PhonemeAudio.SOURCE_UPLOADED
        super().save_model(request, obj, form, change)

    @admin.action(description="Regenerate the selected recordings with ElevenLabs")
    def regenerate(self, request, queryset):
        from .phoneme_audio import make_audio

        made = sum(1 for row in queryset if make_audio(row.key, row.symbol, replace=True))
        self.message_user(request, f"Regenerated {made} of {queryset.count()} recording(s).")

    @admin.action(description="Make every missing chart recording")
    def generate_missing(self, request, queryset):
        from .phoneme_audio import fill_missing

        made = fill_missing()
        self.message_user(request, f"Made {made} missing recording(s).")
