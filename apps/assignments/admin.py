from django.contrib import admin

from .models import Assignment


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["__str__", "school", "kind", "due_on", "created_by"]
    list_filter = ["kind", "due_on"]
    raw_id_fields = ["created_by", "group", "module_day", "lesson", "assessment"]
    filter_horizontal = ["classes"]
