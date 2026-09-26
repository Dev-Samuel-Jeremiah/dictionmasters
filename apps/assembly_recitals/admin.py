from django.contrib import admin

from apps.book.video_admin import VideoPosterAdminMixin

from .models import Recital, Section


class RecitalInline(admin.TabularInline):
    model = Recital
    extra = 0
    fields = ["order", "title", "is_published"]
    show_change_link = True


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["name", "icon", "order", "is_published"]
    list_filter = ["is_published"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [RecitalInline]


@admin.register(Recital)
class RecitalAdmin(VideoPosterAdminMixin, admin.ModelAdmin):
    list_display = ["title", "section", "order", "is_published"]
    list_filter = ["section", "is_published"]
    search_fields = ["title", "summary", "lines"]
    prepopulated_fields = {"slug": ("title",)}
