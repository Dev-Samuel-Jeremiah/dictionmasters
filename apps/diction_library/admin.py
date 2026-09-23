from django.contrib import admin

from .models import LibraryItem


@admin.register(LibraryItem)
class LibraryItemAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "visibility_label", "is_published", "created_at"]
    list_filter = ["kind", "is_published", "school"]
    search_fields = ["title", "summary", "description", "school__name"]
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ["school", "created_by"]

    def visibility_label(self, obj):
        return obj.visibility_label
    visibility_label.short_description = "Visible to"
