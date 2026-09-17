from django.contrib import admin

from .models import BillingSettings, Payment, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "audience", "band_label", "price", "duration_days", "is_featured", "is_active", "order")
    list_filter = ("audience", "is_active")
    list_editable = ("is_active", "order")
    search_fields = ("name", "description")
    readonly_fields = ("slug",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "plan", "trial_ends_at", "paid_until", "updated_at")
    search_fields = ("user__email", "school__name")
    raw_id_fields = ("user", "school")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "account_name", "plan_name", "amount_display", "status", "channel", "paid_at", "created_at")
    list_filter = ("status", "channel")
    search_fields = ("reference", "email", "account_name")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False


admin.site.register(BillingSettings)
