from django.contrib import admin

from apps.book.video_admin import VideoPosterAdminMixin

from .models import Dialogue, DialogueLevel, DialogueProgress


@admin.register(DialogueLevel)
class DialogueLevelAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "is_published"]
    list_filter = ["is_published"]


@admin.register(Dialogue)
class DialogueAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    list_display = ["title", "level", "term", "week", "day", "is_published"]
    list_filter = ["level", "term", "week", "day", "is_published"]
    search_fields = ["title", "target_words", "script"]


@admin.register(DialogueProgress)
class DialogueProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "dialogue", "completed_at"]
    readonly_fields = ["completed_at"]
