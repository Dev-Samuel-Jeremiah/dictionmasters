from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import Answer, Assessment, Attempt, Question


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1
    fields = [
        ("order", "type", "points", "level"),
        "prompt", "word", "options", "answer", "explanation",
        ("audio_file", "audio_url"), "image",
    ]


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "level", "questions_count", "time_limit_minutes", "max_attempts", "attempts_count", "is_published"]
    list_filter = ["kind", "level", "is_published"]
    search_fields = ["title", "summary"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [QuestionInline]
    fieldsets = [
        (None, {"fields": ["title", "slug", "kind", "summary", "is_published", "order"]}),
        ("Rules", {
            "fields": [("time_limit_minutes", "pass_mark", "max_attempts"), "shuffle_questions", "level"],
            "description": "Timed tests need a time limit. Placement tests use each question's level instead of the one here.",
        }),
        ("For the learner", {"fields": ["instructions"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_questions=Count("questions", distinct=True), _attempts=Count("attempts", distinct=True))

    @admin.display(description="Questions", ordering="_questions")
    def questions_count(self, obj):
        return obj._questions

    @admin.display(description="Attempts", ordering="_attempts")
    def attempts_count(self, obj):
        return obj._attempts


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    can_delete = False
    fields = ["question", "given", "recording", "is_correct", "points_awarded"]
    readonly_fields = ["question", "given", "recording", "is_correct", "points_awarded"]


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ["user", "assessment", "status", "percent", "grade", "recommended_level", "submitted_at", "mark_link"]
    list_filter = ["status", "assessment__kind", "assessment"]
    search_fields = ["user__email", "user__first_name", "assessment__title"]
    date_hierarchy = "started_at"
    readonly_fields = [
        "user", "assessment", "status", "started_at", "deadline_at", "submitted_at",
        "score", "max_score", "percent", "passed", "grade", "recommended_level", "marked_by", "marked_at",
    ]
    fields = readonly_fields + ["feedback"]
    inlines = [AnswerInline]

    def has_add_permission(self, request):
        return False

    @admin.display(description="")
    def mark_link(self, obj):
        if obj.status == Attempt.Status.AWAITING:
            return format_html('<a href="{}">Mark on site &rarr;</a>', reverse("assessments:mark", args=[obj.pk]))
        if obj.status != Attempt.Status.IN_PROGRESS:
            return format_html('<a href="{}">View result</a>', reverse("assessments:result", args=[obj.pk]))
        return ""
