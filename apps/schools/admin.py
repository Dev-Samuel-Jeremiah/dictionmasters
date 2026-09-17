from django.contrib import admin

from .models import AccessCode, School


class AccessCodeInline(admin.TabularInline):
    model = AccessCode
    extra = 0
    fields = ["code", "role", "label", "used_by", "created_at"]
    readonly_fields = ["code", "used_by", "created_at"]


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "email", "phone", "created_at"]
    search_fields = ["name", "code", "email"]
    readonly_fields = ["code", "created_at"]
    inlines = [AccessCodeInline]


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "school", "role", "level", "label", "used_by", "created_at"]
    list_filter = ["role", "level", "school"]
    search_fields = ["code", "label", "school__name"]
    readonly_fields = ["code", "used_by", "used_at", "created_at"]
