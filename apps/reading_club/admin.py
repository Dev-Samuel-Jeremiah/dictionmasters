from django.contrib import admin

from apps.book.video_admin import VideoPosterAdminMixin

from .models import Book, Chapter, ChapterProgress, ChapterResource, Term


class TermInline(admin.TabularInline):
    model = Term
    extra = 1
    fields = ["order", "name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ["title", "author", "icon", "color", "order", "is_published", "term_count"]
    list_filter = ["is_published"]
    search_fields = ["title", "author", "description"]
    prepopulated_fields = {"slug": ("title",)}
    ordering = ["order"]
    inlines = [TermInline]
    fieldsets = [
        (None, {
            "fields": ["title", "slug", "author", "order", "is_published"],
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


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 1
    fields = ["number", "title", "is_published"]
    show_change_link = True


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["name", "book", "order", "chapter_count"]
    list_filter = ["book"]
    search_fields = ["name", "book__title"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ChapterInline]

    def chapter_count(self, obj):
        return obj.chapters.count()
    chapter_count.short_description = "Chapters"


class ChapterResourceInline(admin.TabularInline):
    model = ChapterResource
    extra = 1
    fields = ["order", "title", "file", "url"]


@admin.register(Chapter)
class ChapterAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    list_display = ["display_name", "term", "is_published", "poster_preview"]
    list_filter = ["term__book", "term", "is_published"]
    search_fields = ["title", "summary", "body"]
    inlines = [ChapterResourceInline]
    fieldsets = [
        (None, {
            "fields": ["term", "number", "title", "summary", "is_published"],
        }),
        ("Text", {
            "fields": ["body"],
        }),
        ("Audio (model reading)", {
            "fields": [("audio_file", "audio_url")],
        }),
        ("Video", {
            "fields": [("video_file", "video_url"), ("video_caption", "video_duration_label"), "video_poster"],
        }),
    ]


@admin.register(ChapterProgress)
class ChapterProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "chapter", "completed_at"]
    list_filter = ["chapter__term__book"]
    search_fields = ["user__email"]
    date_hierarchy = "completed_at"

    def has_add_permission(self, request):
        return False
