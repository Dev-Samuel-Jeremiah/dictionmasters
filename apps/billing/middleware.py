from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .access import GATED_PREFIXES, has_access, is_exempt, subscription_for
from .models import BillingSettings

# Pages someone with no trial and no plan may still open: paying, and
# getting in and out of their account.
ALWAYS_OPEN = ("/billing/", "/accounts/logout/", "/accounts/login/", "/static/", "/media/", "/manage/", "/admin/")
DASHBOARDS = ("/accounts/dashboard/", "/school/dashboard/")


class SubscriptionRequiredMiddleware:
    """Keep the learning tools for people whose trial or plan is running.

    Signed-out visitors pass through (each tool asks them to log in
    itself), and so does everything outside the tools: the dashboard,
    billing, account and school pages always stay open."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not is_exempt(user) and not request.path.startswith(ALWAYS_OPEN):
            # Every account is on its trial or a plan before it sees anything:
            # this starts the trial for an account that hasn't had one.
            subscription = subscription_for(user)
            if (
                subscription is not None
                and request.path.startswith(DASHBOARDS)
                and subscription.trial_ends_at is None and subscription.paid_until is None
                and BillingSettings.load().paywall_enabled
            ):
                return redirect(reverse("billing:account"))

        if (
            user is not None
            and user.is_authenticated
            and request.path.startswith(GATED_PREFIXES)
            and not has_access(user)
        ):
            plans = reverse("billing:account")
            wants_json = (
                request.method != "GET"
                or "application/json" in request.headers.get("Accept", "")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if wants_json:
                return JsonResponse(
                    {"error": "subscription_required", "message": "Your access has ended. Choose a plan to carry on.", "url": plans},
                    status=402,
                )
            return redirect(f"{plans}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
