from django.contrib import admin

from .models import LibraryArticle, LibraryAttachment, LibraryCategory, LibraryTag


@admin.register(LibraryCategory)
class LibraryCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "article_count"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["order"]

    def article_count(self, obj):
        return obj.articles.count()
    article_count.short_description = "Articles"


@admin.register(LibraryTag)
class LibraryTagAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]


class LibraryAttachmentInline(admin.TabularInline):
    model = LibraryAttachment
    extra = 1
    fields = ["order", "title", "file", "url"]


@admin.register(LibraryArticle)
class LibraryArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "is_published", "order", "updated_at"]
    list_filter = ["category", "is_published", "tags"]
    search_fields = ["title", "summary", "body"]
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ["tags"]
    inlines = [LibraryAttachmentInline]
    fieldsets = [
        (None, {"fields": ["category", "title", "slug", "summary", "body"]}),
        ("Cross-referencing", {"fields": ["tags", "source_credit", "external_link"]}),
        ("Visibility", {"fields": ["is_published", "order"]}),
    ]
