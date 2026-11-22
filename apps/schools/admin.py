from django.contrib import admin

from .models import AccessCode, ExtraTeacherAccess, School, SchoolClass


class AccessCodeInline(admin.TabularInline):
    model = AccessCode
    extra = 0
    fields = ["code", "role", "label", "used_by", "created_at"]
    readonly_fields = ["code", "used_by", "created_at"]


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "email", "contact_person", "phone", "relationship_status", "created_at"]
    search_fields = ["name", "code", "email", "contact_person", "phone"]
    readonly_fields = ["code", "created_at"]
    inlines = [AccessCodeInline]


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "school", "role", "level", "label", "used_by", "created_at"]
    list_filter = ["role", "level", "school"]
    search_fields = ["code", "label", "school__name"]
    readonly_fields = ["code", "used_by", "used_at", "created_at"]


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ["display_name", "school", "session", "grade", "class_teacher"]
    list_filter = ["grade", "session"]
    search_fields = ["name", "school__name"]
    filter_horizontal = ["teachers"]


@admin.register(ExtraTeacherAccess)
class ExtraTeacherAccessAdmin(admin.ModelAdmin):
    """A record of extra teachers' access. Given and taken back in the control
    room (Schools & people > a school > Teacher places), so every change is
    logged there; here it's only read."""
    list_display = ["school", "teachers", "reason", "ends_on", "granted_by", "created_at", "ended_at"]
    list_filter = ["ended_at"]
    search_fields = ["school__name", "reason"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

