from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["email", "first_name", "last_name", "role", "level_display", "school", "is_active", "date_joined"]
    list_filter = ["role", "level", "is_active", "is_staff", "school"]
    search_fields = ["email", "first_name", "last_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Role, level & school", {
            "fields": ("role", "level", "school"),
            "description": "A teacher or student sees only their level's work. "
                           "Leave the level blank to open every level to them.",
        }),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "school", "password1", "password2"),
        }),
    )
    readonly_fields = ["date_joined"]

    @admin.display(description="Level", ordering="level")
    def level_display(self, obj):
        return obj.level or "Every level"

    # Only a superuser gives control room access or changes a staff account
    # (November 2026; the control room's own screens do the same).
    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            fields += ["is_staff", "is_superuser", "groups", "user_permissions"]
        return fields

    def _guards_staff(self, request, obj):
        return (obj is not None and (obj.is_staff or obj.is_superuser) and obj.pk != request.user.pk
                and not request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not self._guards_staff(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not self._guards_staff(request, obj)
