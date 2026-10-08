from django.contrib import admin

from .models import Grading, ReportCard, SchemeEntry, SchoolTermDates, Session, Term


class TermInline(admin.TabularInline):
    model = Term
    extra = 0


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    inlines = [TermInline]


@admin.register(SchemeEntry)
class SchemeEntryAdmin(admin.ModelAdmin):
    list_display = ["level", "term", "week", "day", "kind", "__str__"]
    list_filter = ["level", "term", "kind"]
    raw_id_fields = ["group", "module_day", "dialogue", "sound", "chapter", "recital", "library_item", "assessment"]


admin.site.register(Grading)
admin.site.register(SchoolTermDates)


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ["student", "term", "total", "grade", "published_at"]
    list_filter = ["term", "grade"]
    raw_id_fields = ["student", "comment_by", "published_by"]
