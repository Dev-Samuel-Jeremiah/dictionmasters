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
