from django.contrib import admin

from .models import Match, Round


class RoundInline(admin.TabularInline):
    model = Round
    extra = 0
    can_delete = False
    fields = ["number", "kind", "word", "answer", "given", "is_correct", "timed_out", "points"]
    readonly_fields = fields


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["user", "mode", "difficulty", "score", "correct", "wrong", "best_streak", "status", "started_at"]
    list_filter = ["mode", "difficulty", "status"]
    search_fields = ["user__email", "user__first_name"]
    date_hierarchy = "started_at"
    readonly_fields = ["user", "mode", "difficulty", "seed", "status", "score", "correct", "wrong",
                       "streak", "best_streak", "lives", "started_at", "ends_at", "finished_at"]
    inlines = [RoundInline]

    def has_add_permission(self, request):
        return False
