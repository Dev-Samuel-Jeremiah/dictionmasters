from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "kind", "created_at", "read_at"]
    list_filter = ["kind"]
    search_fields = ["title", "user__email", "user__first_name"]
    raw_id_fields = ["user"]
