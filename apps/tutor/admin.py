from django.contrib import admin

from .models import TutorPassage, TutorSession, TutorSpeech


@admin.register(TutorPassage)
class TutorPassageAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "order", "is_published")
    list_filter = ("level", "is_published")
    search_fields = ("title", "body")


@admin.register(TutorSession)
class TutorSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "status", "accuracy", "wcpm", "reading_level", "started_at")
    list_filter = ("status", "band", "reading_level")
    search_fields = ("user__email", "title")
    readonly_fields = [field.name for field in TutorSession._meta.fields]


@admin.register(TutorSpeech)
class TutorSpeechAdmin(admin.ModelAdmin):
    list_display = ("text", "created_at")
    search_fields = ("text",)
