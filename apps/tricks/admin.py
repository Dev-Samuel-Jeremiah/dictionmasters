from django.contrib import admin

from .models import TrickActivity, TrickActivityAttempt, TrickActivityItem, TrickProgress


class TrickActivityItemInline(admin.StackedInline):
    model = TrickActivityItem
    extra = 1
    fields = [("order", "hint"), "prompt", "answer", "options", ("audio_file", "audio_url"), "image"]


@admin.register(TrickActivity)
class TrickActivityAdmin(admin.ModelAdmin):
    list_display = ["title", "trick", "kind", "pass_mark", "order", "is_published"]
    list_filter = ["kind", "is_published", "trick"]
    search_fields = ["title", "trick__name"]
    inlines = [TrickActivityItemInline]
    fields = ["trick", "kind", "title", "instructions", "buckets", ("pass_mark", "order", "is_published"),
              ("audio_file", "audio_url"), ("video_file", "video_url")]


@admin.register(TrickActivityAttempt)
class TrickActivityAttemptAdmin(admin.ModelAdmin):
    list_display = ["user", "activity", "percent", "passed", "status", "created_at"]
    list_filter = ["status", "passed", "activity__trick"]
    search_fields = ["user__email", "activity__title"]
    readonly_fields = ["user", "activity", "score", "max_score", "percent", "passed", "created_at"]
    fields = readonly_fields + ["status", "teacher_score", "teacher_feedback"]


@admin.register(TrickProgress)
class TrickProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "trick", "updated_at"]
    search_fields = ["user__email", "trick__name"]
