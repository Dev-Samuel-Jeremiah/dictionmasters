from django.contrib import admin

from apps.book.video_admin import VideoPosterAdminMixin

from .activity_kinds import field_visibility

from .models import (
    Activity,
    ActivityAttempt,
    ActivityItem,
    ActivityResponse,
    CardLesson,
    Category,
    Dialogue,
    DialogueLine,
    Group,
    GroupProgress,
    Level,
    Passage,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "icon", "color", "order"]
    list_filter = ["kind"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["order"]
    fieldsets = [
        (None, {"fields": ["name", "slug", "kind", "order"]}),
        ("Badge", {"fields": [("icon", "color")]}),
        ("Copy", {"fields": ["description"]}),
    ]


class GroupInline(admin.TabularInline):
    model = Group
    extra = 1
    fields = ["number", "title"]
    show_change_link = True


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ["name", "age_range", "order", "is_published", "group_count", "category_list"]
    list_filter = ["is_published"]
    search_fields = ["name", "age_range", "description"]
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ["categories"]
    ordering = ["order"]
    inlines = [GroupInline]
    fieldsets = [
        (None, {"fields": ["name", "slug", "age_range", "order", "is_published"]}),
        ("Copy", {"fields": ["description"]}),
        ("Cards available in this level", {"fields": ["categories"]}),
    ]

    class Media:
        js = ["js/echospell_admin.js"]

    def group_count(self, obj):
        return obj.groups.count()
    group_count.short_description = "Groups"

    def category_list(self, obj):
        return ", ".join(obj.categories.values_list("name", flat=True)) or "—"
    category_list.short_description = "Cards"


class CardLessonInline(admin.TabularInline):
    model = CardLesson
    extra = 1
    fields = ["order", "category", "word", "ipa", "audio_url", "is_published"]
    show_change_link = True
    verbose_name = "Card"
    verbose_name_plural = "Cards — each category's own words, audio and video for this group"


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ["display_name", "level", "card_count"]
    list_filter = ["level"]
    inlines = [CardLessonInline]

    def card_count(self, obj):
        return obj.lessons.count()
    card_count.short_description = "Cards"


@admin.register(CardLesson)
class CardLessonAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    list_display = ["word_display", "group", "category", "order", "is_published", "poster_preview"]
    list_filter = ["group__level", "category"]
    search_fields = ["word", "title", "body", "definition", "ipa"]
    fieldsets = [
        (None, {"fields": ["group", "category", "title", "order", "is_published"]}),
        ("Word", {"fields": ["word", "ipa"]}),
        ("Meaning", {"fields": ["definition", "example_sentence", "image"]}),
        ("Notes", {"fields": ["body"]}),
        ("Video", {"fields": [("video_file", "video_url"), ("video_caption", "video_duration_label"), "video_poster"]}),
        ("Audio", {"fields": [("audio_file", "audio_url")]}),
    ]

    def word_display(self, obj):
        return ", ".join(obj.word_list) or obj.title or "—"
    word_display.short_description = "Word(s)"


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    list_display = ["__str__", "group"]
    list_filter = ["group__level"]
    fieldsets = [
        (None, {"fields": ["group", "title"]}),
        ("Text", {"fields": ["body"]}),
        ("Audio", {"fields": [("audio_file", "audio_url")]}),
    ]


class DialogueLineInline(admin.TabularInline):
    model = DialogueLine
    extra = 2
    fields = ["order", "speaker", "text"]


@admin.register(Dialogue)
class DialogueAdmin(admin.ModelAdmin):
    list_display = ["__str__", "group", "line_count"]
    list_filter = ["group__level"]
    inlines = [DialogueLineInline]
    fieldsets = [
        (None, {"fields": ["group", "title"]}),
        ("Audio", {"fields": [("audio_file", "audio_url")]}),
    ]

    def line_count(self, obj):
        return obj.lines.count()
    line_count.short_description = "Lines"


@admin.register(GroupProgress)
class GroupProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "group", "completed_at"]
    list_filter = ["group__level"]
    search_fields = ["user__email"]
    date_hierarchy = "completed_at"

    def has_add_permission(self, request):
        return False


class ActivityItemInline(admin.StackedInline):
    model = ActivityItem
    extra = 1
    fields = ["order", "prompt", "answer", "options", "hint", ("audio_file", "audio_url"), "image"]
    verbose_name = "Question"
    verbose_name_plural = "Questions"

    def get_formset(self, request, obj=None, **kwargs):
        """Relabel the question fields to suit the activity's kind — an
        "answer" means something quite different for a transcription
        than it does for a sound sort."""
        formset = super().get_formset(request, obj, **kwargs)
        kind = obj.kind_spec if obj else None
        if kind:
            fields = formset.form.base_fields
            fields["prompt"].help_text = kind.prompt_help
            fields["answer"].help_text = kind.answer_help
            fields["options"].help_text = kind.options_help or "Not used by this kind of activity."
        return formset


@admin.register(Activity)
class ActivityAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    change_form_template = "admin/echospell/activity/change_form.html"
    list_display = ["title", "kind_badge", "group", "question_count", "pass_mark", "is_published", "poster_preview"]
    list_filter = ["group__level", "kind", "is_published"]
    search_fields = ["title", "instructions"]
    prepopulated_fields = {"slug": ("title",)}
    ordering = ["group", "order"]
    inlines = [ActivityItemInline]
    fieldsets = [
        (None, {"fields": ["title", "slug", "kind", "order", "is_published"]}),
        ("Where it belongs", {"fields": ["group"]}),
        ("How it is presented", {"fields": ["instructions", "pass_mark"]}),
        ("Sound sort boxes", {
            "fields": ["buckets"],
            "description": "Only used by the Sound sort kind — ignore it for everything else.",
        }),
        ("Media", {
            "classes": ["collapse"],
            "fields": [("audio_file", "audio_url"), ("video_file", "video_url"), "video_poster"],
        }),
    ]

    class Media:
        js = ["js/echospell_activity_admin.js"]
        css = {"all": ["css/echospell_admin.css"]}

    def render_change_form(self, request, context, *args, **kwargs):
        """Hand the kind catalogue to the form so its JavaScript can lock
        the fields the chosen kind doesn't use."""
        context["kind_field_map"] = field_visibility()
        return super().render_change_form(request, context, *args, **kwargs)

    def kind_badge(self, obj):
        return f"{obj.icon} {obj.kind_label}"
    kind_badge.short_description = "Activity type"

    def question_count(self, obj):
        return obj.items.count()
    question_count.short_description = "Questions"


class ActivityResponseInline(admin.TabularInline):
    model = ActivityResponse
    extra = 0
    fields = ["item", "given", "recording", "is_correct"]
    readonly_fields = ["item", "given", "recording"]
    can_delete = False


@admin.register(ActivityAttempt)
class ActivityAttemptAdmin(admin.ModelAdmin):
    list_display = ["user", "activity", "percent", "passed", "status", "created_at"]
    list_filter = ["status", "passed", "activity__group__level", "activity__kind"]
    search_fields = ["user__email", "activity__title"]
    readonly_fields = ["user", "activity", "score", "max_score", "percent", "passed", "created_at"]
    inlines = [ActivityResponseInline]
    fieldsets = [
        (None, {"fields": ["user", "activity", "created_at"]}),
        ("Automatic marking", {"fields": [("score", "max_score"), ("percent", "passed")]}),
        ("Teacher's marking", {
            "fields": ["status", "teacher_score", "teacher_feedback"],
            "description": "For recorded activities: listen below, then score out of 100 and leave feedback.",
        }),
    ]

    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
