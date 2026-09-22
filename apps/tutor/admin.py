from django.contrib import admin

from .models import TutorChoice, TutorPassage, TutorSession, TutorSpeech, TutorVoice


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


@admin.register(TutorVoice)
class TutorVoiceAdmin(admin.ModelAdmin):
    list_display = ["name", "gender", "avatar", "voice_id", "is_default", "is_active", "order"]
    list_filter = ["gender", "is_active"]
    search_fields = ["name", "description"]
    fields = ["name", "gender", "avatar", "description", "voice_id", "sample_text",
              ("order", "is_default", "is_active")]


@admin.register(TutorChoice)
class TutorChoiceAdmin(admin.ModelAdmin):
    list_display = ["user", "voice", "updated_at"]
    search_fields = ["user__email", "voice__name"]
    readonly_fields = ["user", "updated_at"]
