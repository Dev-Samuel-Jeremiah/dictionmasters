from django.contrib import admin

from .models import Grading, ReportCard, SchemeWeek, SchoolTermDates, Session, Term


class TermInline(admin.TabularInline):
    model = Term
    extra = 0


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    inlines = [TermInline]


@admin.register(SchemeWeek)
class SchemeWeekAdmin(admin.ModelAdmin):
    list_display = ["level", "term", "week", "title"]
    list_filter = ["level", "term"]
    filter_horizontal = ["groups"]


admin.site.register(Grading)
admin.site.register(SchoolTermDates)


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ["student", "term", "total", "grade", "published_at"]
    list_filter = ["term", "grade"]
    raw_id_fields = ["student", "comment_by", "published_by"]
