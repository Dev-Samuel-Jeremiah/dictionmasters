"""
Diction Masters inside the Android and iPhone apps.

The phone apps (the separate `mobile/` project) are a native shell that
opens this website. Because every page still comes from Django, whatever
you change or add here shows up in both apps as soon as it is deployed —
no app-store update needed.

The app adds "DictionMastersApp/android" or "DictionMastersApp/ios" to its
User-Agent, which is how Django knows a request came from the app. This
module uses that to:

  * put `native_app` in every template ({{ native_app.platform }},
    {% if native_app %} ... {% endif %}) and load static/js/native_app.js,
    which adds the phone features (back button, downloads, sharing, ...)
  * open the app on a proper welcome screen instead of the marketing page
  * follow the app-store payment rules: Apple (and Google Play) don't allow
    selling digital subscriptions inside an app through your own payment
    provider (Paystack). So, on the platforms listed in
    NATIVE_APP_HIDE_PAYMENTS, buying pages show a short notice instead and
    purchase buttons are hidden. People still use everything they paid for
    on the website. See MOBILE_APP_GUIDE.md, section 8.
  * serve the two /.well-known/ files that let website links open the app.

Settings (config/settings.py, set from the environment):

  NATIVE_APP_HIDE_PAYMENTS      platforms that hide buying, e.g. ["ios", "android"]
  NATIVE_APP_ANDROID_PACKAGE    the app id, e.g. "app.dictionmasters.mobile"
  NATIVE_APP_ANDROID_SHA256     signing-key fingerprint(s) from Google Play
  NATIVE_APP_IOS_TEAM_ID        your Apple Developer team id (10 characters)
"""

import re

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

_AGENT = re.compile(r"DictionMastersApp/(android|ios)\b", re.IGNORECASE)

# Buying pages. The account page (/billing/) itself stays open: it shows
# the learner's access, and the template hides the plans there.
BUYING_PATHS = ("/billing/plans/", "/billing/checkout/", "/billing/promo/")


def platform_of(request):
    """'android', 'ios', or None when the request didn't come from the app."""
    cached = getattr(request, "_native_platform", False)
    if cached is not False:
        return cached
    match = _AGENT.search(request.headers.get("User-Agent", ""))
    request._native_platform = match.group(1).lower() if match else None
    return request._native_platform


def hides_payments(request):
    platform = platform_of(request)
    return bool(platform) and platform in getattr(settings, "NATIVE_APP_HIDE_PAYMENTS", ("ios", "android"))


class NativeAppMiddleware:
    """Only does anything for requests from the phone apps."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        platform = platform_of(request)
        if platform and request.method == "GET":
            # The app opens on "/": signed-in people go straight to their
            # dashboard, everyone else to the app's welcome screen.
            if request.path == "/":
                user = getattr(request, "user", None)
                if user is not None and user.is_authenticated:
                    return redirect("accounts:dashboard")
                return redirect("native_app_welcome")
        if platform and hides_payments(request) and request.path.startswith(BUYING_PATHS):
            return render(request, "native_app/billing_notice.html", status=200)

        response = self.get_response(request)
        if platform:
            # Pages differ between the app and the browser: keep caches apart.
            response["Vary"] = ", ".join(filter(None, [response.get("Vary"), "User-Agent"]))
        return response


def app_downloads():
    """Where people can get the apps (config/settings.py). Empty = not offered."""
    return {
        "android_apk": getattr(settings, "NATIVE_APP_ANDROID_APK_URL", ""),
        "android_store": getattr(settings, "NATIVE_APP_ANDROID_STORE_URL", ""),
        "ios_store": getattr(settings, "NATIVE_APP_IOS_STORE_URL", ""),
    }


def context(request):
    """In every template:

    `native_app`     None in a browser, otherwise
                     {"platform": "android"|"ios", "hide_payments": bool}
    `app_downloads`  where the apps can be downloaded (see app_downloads)"""
    platform = platform_of(request)
    downloads = app_downloads()
    if not platform:
        return {"native_app": None, "app_downloads": downloads}
    return {"native_app": {"platform": platform, "hide_payments": hides_payments(request)},
            "app_downloads": downloads}


def device_of(request):
    """'android', 'ios' or 'desktop', from the browser's description of itself."""
    agent = request.headers.get("User-Agent", "")
    if re.search(r"Android", agent):
        return "android"
    if re.search(r"iPhone|iPad|iPod", agent) or ("Macintosh" in agent and "Mobile" in agent):
        return "ios"
    return "desktop"


def get_app(request):
    """/app/get/ — the "Get the app" page: the Android app to download, the
    App Store, or "Add to Home Screen" on iPhone, whichever fits the phone
    it's opened on. Already inside the app, there's nothing to get."""
    if platform_of(request):
        return redirect("accounts:dashboard")
    from apps.echospell.qr import svg

    page = request.build_absolute_uri(request.path) if settings.DEBUG else f"{settings.SITE_URL}{request.path}"
    return render(request, "native_app/get_app.html", {
        "device": device_of(request),
        "downloads": app_downloads(),
        "qr": svg(page, 180),
        "page_url": page,
    })


def welcome(request):
    """The first screen of the app for someone who isn't signed in."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return render(request, "native_app/welcome.html")


# ------------------------------------------------------------ deep links

@cache_control(max_age=3600, public=True)
def android_asset_links(request):
    """/.well-known/assetlinks.json — lets Android open website links in the app."""
    package = getattr(settings, "NATIVE_APP_ANDROID_PACKAGE", "")
    fingerprints = list(getattr(settings, "NATIVE_APP_ANDROID_SHA256", []))
    if not package or not fingerprints:
        return JsonResponse([], safe=False)
    return JsonResponse([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": package,
            "sha256_cert_fingerprints": fingerprints,
        },
    }], safe=False)


@cache_control(max_age=3600, public=True)
def apple_app_site_association(request):
    """/.well-known/apple-app-site-association — the same, for iPhone."""
    team = getattr(settings, "NATIVE_APP_IOS_TEAM_ID", "")
    bundle = getattr(settings, "NATIVE_APP_IOS_BUNDLE_ID", "") or getattr(settings, "NATIVE_APP_ANDROID_PACKAGE", "")
    if not team or not bundle:
        return HttpResponse("{}", content_type="application/json", status=404)
    return JsonResponse({
        "applinks": {
            "details": [{
                "appIDs": [f"{team}.{bundle}"],
                # Everything except staff and payment-provider pages.
                "components": [
                    {"/": "/admin/*", "exclude": True},
                    {"/": "/manage/*", "exclude": True},
                    {"/": "/billing/webhook/*", "exclude": True},
                    {"/": "/*"},
                ],
            }],
        },
    })
