from django.contrib import admin

from .models import LessonActivity, LessonActivityAttempt, LessonActivityItem, LessonProgress


class LessonActivityItemInline(admin.StackedInline):
    model = LessonActivityItem
    extra = 1
    fields = [("order", "hint"), "prompt", "answer", "options", ("audio_file", "audio_url"), "image"]


@admin.register(LessonActivity)
class LessonActivityAdmin(admin.ModelAdmin):
    list_display = ["title", "lesson", "kind", "pass_mark", "order", "is_published"]
    list_filter = [("lesson__category__programme", admin.ChoicesFieldListFilter), "kind", "is_published"]
    search_fields = ["title", "lesson__name"]
    inlines = [LessonActivityItemInline]
    fields = ["lesson", "kind", "title", "instructions", "buckets", ("pass_mark", "order", "is_published")]


@admin.register(LessonActivityAttempt)
class LessonActivityAttemptAdmin(admin.ModelAdmin):
    list_display = ["user", "activity", "percent", "passed", "status", "created_at"]
    list_filter = ["status", "passed", ("activity__lesson__category__programme", admin.ChoicesFieldListFilter)]
    search_fields = ["user__email", "activity__title"]
    readonly_fields = ["user", "activity", "score", "max_score", "percent", "passed", "created_at"]
    fields = readonly_fields + ["status", "teacher_score", "teacher_feedback"]


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "lesson", "updated_at"]
    search_fields = ["user__email", "lesson__name"]
