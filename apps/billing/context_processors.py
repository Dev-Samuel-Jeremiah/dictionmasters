from django.utils.functional import SimpleLazyObject


def billing(request):
    """`billing` in every template: the signed-in person's access, for the
    trial and renewal banner. Only looked up on pages that use it."""

    def load():
        from .access import status_for

        return status_for(request.user) if hasattr(request, "user") else None

    def load_settings():
        from .models import BillingSettings

        return BillingSettings.load()

    return {
        "billing": SimpleLazyObject(lambda: load() or {}),
        "billing_settings": SimpleLazyObject(load_settings),
    }
