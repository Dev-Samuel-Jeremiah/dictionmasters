from django.contrib import admin

from apps.book.video_admin import VideoPosterAdminMixin

from .models import Day, DayProgress, LearningModule, LessonItem, LessonResource, Term, Week


class TermInline(admin.TabularInline):
    model = Term
    extra = 1
    fields = ["order", "name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(LearningModule)
class LearningModuleAdmin(admin.ModelAdmin):
    list_display = ["name", "icon", "color", "order", "is_published", "term_count"]
    list_filter = ["is_published"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["order"]
    inlines = [TermInline]
    fieldsets = [
        (None, {
            "fields": ["name", "slug", "order", "is_published"],
        }),
        ("Badge", {
            "fields": [("icon", "color")],
        }),
        ("Copy", {
            "fields": ["description", "overview"],
        }),
    ]

    def term_count(self, obj):
        return obj.terms.count()
    term_count.short_description = "Terms"


class WeekInline(admin.TabularInline):
    model = Week
    extra = 1
    fields = ["number", "title"]


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["name", "module", "order", "week_count"]
    list_filter = ["module"]
    search_fields = ["name", "module__name"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [WeekInline]

    def week_count(self, obj):
        return obj.weeks.count()
    week_count.short_description = "Weeks"


class DayInline(admin.TabularInline):
    model = Day
    extra = 1
    fields = ["day_name", "is_published"]
    show_change_link = True


@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ["display_name", "term", "day_count"]
    list_filter = ["term__module", "term"]
    inlines = [DayInline]

    def day_count(self, obj):
        return obj.days.count()
    day_count.short_description = "Days"


class LessonItemInline(admin.TabularInline):
    model = LessonItem
    extra = 1
    fields = ["order", "title", "video_url", "audio_url", "is_published"]
    show_change_link = True


@admin.register(Day)
class DayAdmin(admin.ModelAdmin):
    list_display = ["__str__", "day_name", "week", "is_published", "item_count"]
    list_filter = ["week__term__module", "week__term", "day_name", "is_published"]
    inlines = [LessonItemInline]

    def item_count(self, obj):
        return obj.lesson_items.count()
    item_count.short_description = "Items"


class LessonResourceInline(admin.TabularInline):
    model = LessonResource
    extra = 1
    fields = ["order", "title", "file", "url"]


@admin.register(LessonItem)
class LessonItemAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    list_display = ["title", "day", "kind", "order", "is_published", "poster_preview"]
    list_filter = ["day__week__term__module", "is_published"]
    search_fields = ["title", "description", "body"]
    inlines = [LessonResourceInline]
    fieldsets = [
        (None, {
            "fields": ["day", "title", "description", "order", "is_published"],
        }),
        ("Text", {
            "fields": ["body"],
        }),
        ("Video", {
            "fields": [("video_file", "video_url"), ("video_caption", "video_duration_label"), "video_poster"],
        }),
        ("Audio", {
            "fields": [("audio_file", "audio_url")],
        }),
    ]


@admin.register(DayProgress)
class DayProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "day", "completed_at"]
    list_filter = ["day__week__term__module"]
    search_fields = ["user__email"]
    date_hierarchy = "completed_at"

    def has_add_permission(self, request):
        return False
