from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .access import GATED_PREFIXES, has_access


class SubscriptionRequiredMiddleware:
    """Keep the learning tools for people whose trial or plan is running.

    Signed-out visitors pass through (each tool asks them to log in
    itself), and so does everything outside the tools: the dashboard,
    billing, account and school pages always stay open."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
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
