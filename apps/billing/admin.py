from django.contrib import admin

from .models import BillingSettings, Payment, Plan, PromoCode, PromoRedemption, Subscription


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


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "discount_label", "state", "used", "max_uses", "starts_at", "expires_at", "is_active"]
    list_filter = ["kind", "is_active"]
    search_fields = ["code", "note"]
    filter_horizontal = ["plans"]
    readonly_fields = ["created_at"]
    fieldsets = [
        (None, {"fields": ["code", "note", "is_active"],
                "description": "Leave the code blank and one is made for you, in the house style (JDM201)."}),
        ("How much off", {"fields": [("kind", "value")]}),
        ("Limits", {"fields": ["max_uses", "once_per_account", ("starts_at", "expires_at"), "plans"]}),
        ("History", {"fields": ["created_at"]}),
    ]

    @admin.display(description="Uses")
    def used(self, obj):
        return obj.used


@admin.register(PromoRedemption)
class PromoRedemptionAdmin(admin.ModelAdmin):
    list_display = ["promo", "user", "amount_off", "payment", "created_at"]
    search_fields = ["promo__code", "user__email"]
    readonly_fields = ["promo", "user", "payment", "amount_off", "created_at"]

    def has_add_permission(self, request):
        return False
