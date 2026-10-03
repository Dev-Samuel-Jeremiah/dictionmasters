from django.contrib import admin

from .models import KeyWord, LessonNote


class KeyWordInline(admin.TabularInline):
    model = KeyWord
    extra = 0
    fields = ("word", "ipa", "syllables", "meaning", "mastered", "attempts")


@admin.register(LessonNote)
class LessonNoteAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "subject", "class_level", "source", "audio_status", "updated_at")
    list_filter = ("source", "audio_status")
    search_fields = ("title", "subject", "owner__email", "owner__first_name", "owner__last_name")
    raw_id_fields = ("owner",)
    inlines = [KeyWordInline]
