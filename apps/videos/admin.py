from django.contrib import admin

from .models import OfflineVideoLicense, StudentDevice


@admin.register(StudentDevice)
class StudentDeviceAdmin(admin.ModelAdmin):
    list_display = ["name", "student", "copies_held", "is_active", "last_seen_at", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "student__email", "device_identifier"]
    readonly_fields = ["device_identifier", "created_at", "last_seen_at"]


@admin.register(OfflineVideoLicense)
class OfflineVideoLicenseAdmin(admin.ModelAdmin):
    list_display = ["title", "student", "device", "expires_at", "is_active", "revoked_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "student__email", "device__name"]
    readonly_fields = ["student", "device", "content_type", "object_id", "issued_at"]

    def has_add_permission(self, request):
        return False
