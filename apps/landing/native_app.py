"""
Diction Masters inside the Android, iPhone and computer apps.

The phone apps (the separate `mobile/` project) and the computer app for
Windows, Mac and Linux (the `desktop/` project) are native shells that
open this website. Because every page still comes from Django, whatever
you change or add here shows up in all the apps as soon as it is
deployed — no app-store update or new download needed.

The app adds "DictionMastersApp/android", "DictionMastersApp/ios" or
"DictionMastersApp/desktop" to its User-Agent, which is how Django knows a
request came from the app. This
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
  NATIVE_APP_DESKTOP_DOWNLOAD_URL  where the computer installers are published
                                (DESKTOP_APP_GUIDE.md)

The computer app isn't sold through an app store, so payments stay on
there (it isn't in NATIVE_APP_HIDE_PAYMENTS unless you add "desktop").
"""

import re

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

_AGENT = re.compile(r"DictionMastersApp/(android|ios|desktop)\b", re.IGNORECASE)

# Buying pages. The account page (/billing/) itself stays open: it shows
# the learner's access, and the template hides the plans there.
BUYING_PATHS = ("/billing/plans/", "/billing/checkout/", "/billing/promo/")


def platform_of(request):
    """'android', 'ios', 'desktop', or None when the request didn't come from an app."""
    cached = getattr(request, "_native_platform", False)
    if cached is not False:
        return cached
    match = _AGENT.search(request.headers.get("User-Agent", ""))
    request._native_platform = match.group(1).lower() if match else None
    return request._native_platform


def hides_payments(request):
    platform = platform_of(request)
    return bool(platform) and platform in getattr(settings, "NATIVE_APP_HIDE_PAYMENTS", ("ios", "android"))


def keep_signed_in(request):
    """In the app, stay signed in for NATIVE_APP_SESSION_DAYS (default 180)
    after the last visit, so the app opens (and works offline) without asking
    for the password again. Renewed at most once a day, not on every page.
    Logging out still logs out."""
    user = getattr(request, "user", None)
    session = getattr(request, "session", None)
    if user is None or session is None or not user.is_authenticated:
        return
    from django.utils import timezone

    today = timezone.now().date().isoformat()
    if session.get("app_signed_in_on") == today:
        return
    session["app_signed_in_on"] = today
    session.set_expiry(int(getattr(settings, "NATIVE_APP_SESSION_DAYS", 180)) * 24 * 60 * 60)


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
            keep_signed_in(request)
        return response


# The computer installers, by file name. The names never change between
# versions (desktop/electron-builder.config.js), so these links always
# download the newest one.
DESKTOP_FILES = {
    "windows": "DictionMasters-Setup.exe",
    "windows_legacy": "DictionMasters-Setup-Windows7-8.exe",
    "mac_arm": "DictionMasters-mac-arm64.dmg",
    "mac_intel": "DictionMasters-mac-x64.dmg",
    "mac_legacy": "DictionMasters-mac-legacy-x64.dmg",
    "linux_appimage": "DictionMasters-linux-x86_64.AppImage",
    "linux_deb": "DictionMasters-linux-amd64.deb",
}


# What the big download button says for each installer: (system, detail).
DESKTOP_LABELS = {
    "windows": ("Windows", "Windows 10 and 11 \u00b7 64-bit"),
    "windows_legacy": ("Windows", "Windows 7, 8 and 8.1 \u00b7 32- and 64-bit"),
    "mac_arm": ("Mac", "Mac with Apple chip (M1 or newer) \u00b7 macOS 12 or newer"),
    "mac_intel": ("Mac", "Mac with Intel chip \u00b7 macOS 12 or newer"),
    "mac_legacy": ("Mac", "Older Macs \u00b7 macOS 10.13 to 11"),
    "linux_deb": ("Linux", "Ubuntu, Debian and Linux Mint \u00b7 .deb"),
    "linux_appimage": ("Linux", "Any 64-bit Linux \u00b7 AppImage"),
}

_WINDOWS_NT = re.compile(r"Windows NT (\d+)\.(\d+)")
_MAC_VERSION = re.compile(r"Mac OS X (\d+)[_.](\d+)")


def desktop_installer_for(request):
    """Which installer fits the visitor's computer, from its User-Agent: a key
    of DESKTOP_FILES, or "" for a phone, a Chromebook or anything unknown.

    The User-Agent can't tell everything (an Apple-chip Mac says "Intel", and
    Safari says 10.15 on every newer macOS), so static/js/desktop_download.js
    refines the choice in the browser where it can."""
    agent = request.headers.get("User-Agent", "")
    if device_of(request) != "desktop" or "CrOS" in agent:
        return ""
    if "Windows" in agent:
        nt = _WINDOWS_NT.search(agent)
        if nt and (int(nt.group(1)), int(nt.group(2))) < (10, 0):
            return "windows_legacy"                 # Windows 7, 8 and 8.1
        if not any(mark in agent for mark in ("Win64", "WOW64", "x64", "ARM64", "aarch64")):
            return "windows_legacy"                 # 32-bit Windows 10: the 7/8 installer has a 32-bit app
        return "windows"
    if "Macintosh" in agent or "Mac OS X" in agent:
        mac = _MAC_VERSION.search(agent)
        if mac and (int(mac.group(1)), int(mac.group(2))) < (10, 15):
            return "mac_legacy"                     # macOS 10.14 and older say so
        return "mac_arm"                            # most Macs now; the page script checks for Intel
    if "Linux" in agent or "X11" in agent:
        if any(name in agent for name in ("Fedora", "Red Hat", "SUSE", "Arch", "Manjaro", "CentOS")):
            return "linux_appimage"
        return "linux_deb"
    return ""


def desktop_choice(request, downloads=None):
    """The big download button on "Get the app": {"key", "url", "os", "detail",
    "choices"}, or None when the installers aren't published or the visitor
    isn't on a computer we make one for. `choices` (every installer's link and
    detail) lets the page script switch to a better fit."""
    downloads = desktop_downloads() if downloads is None else downloads
    key = desktop_installer_for(request)
    if not downloads or not key:
        return None
    system, detail = DESKTOP_LABELS[key]
    return {
        "key": key, "url": downloads[key], "os": system, "detail": detail,
        "choices": {name: {"url": downloads[name], "os": DESKTOP_LABELS[name][0], "detail": DESKTOP_LABELS[name][1]}
                    for name in DESKTOP_FILES},
    }


def desktop_downloads():
    """Download links for the computer app, or {} when it isn't published yet."""
    base = (getattr(settings, "NATIVE_APP_DESKTOP_DOWNLOAD_URL", "") or "").rstrip("/")
    if not base:
        return {}
    return {key: f"{base}/{filename}" for key, filename in DESKTOP_FILES.items()}


def app_downloads():
    """Where people can get the apps (config/settings.py). Empty = not offered."""
    return {
        "android_apk": getattr(settings, "NATIVE_APP_ANDROID_APK_URL", ""),
        "android_store": getattr(settings, "NATIVE_APP_ANDROID_STORE_URL", ""),
        "ios_store": getattr(settings, "NATIVE_APP_IOS_STORE_URL", ""),
        "desktop": desktop_downloads(),
    }


def context(request):
    """In every template:

    `native_app`     None in a browser, otherwise
                     {"platform": "android"|"ios"|"desktop", "hide_payments": bool}
    `app_downloads`  where the apps can be downloaded (see app_downloads)
    `desktop_os`     "Windows", "Mac" or "Linux" when the computer app is
                     published and fits the visitor's computer, else ""
                     (the footer's "Get the app for Windows")"""
    platform = platform_of(request)
    downloads = app_downloads()
    if not platform:
        key = desktop_installer_for(request) if downloads["desktop"] else ""
        return {"native_app": None, "app_downloads": downloads,
                "desktop_os": DESKTOP_LABELS[key][0] if key else ""}
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


def computer_of(request):
    """'windows', 'mac', 'linux' or '' — which computer installer to show first."""
    agent = request.headers.get("User-Agent", "")
    if "Windows" in agent:
        return "windows"
    if "Macintosh" in agent or "Mac OS X" in agent:
        return "mac"
    if "CrOS" in agent:
        return ""                                   # a Chromebook: no installer; it installs the website
    if "Linux" in agent or "X11" in agent:
        return "linux"
    return ""


def get_app(request):
    """/app/get/ — the "Get the app" page: the Android app to download, the
    App Store, "Add to Home Screen" on iPhone, or the computer app for
    Windows, Mac or Linux, whichever fits the device it's opened on. Already inside the app, there's nothing to get."""
    if platform_of(request):
        return redirect("accounts:dashboard")
    from apps.echospell.qr import svg

    page = request.build_absolute_uri(request.path) if settings.DEBUG else f"{settings.SITE_URL}{request.path}"
    return render(request, "native_app/get_app.html", {
        "device": device_of(request),
        "computer": computer_of(request),
        "downloads": app_downloads(),
        "desktop_choice": desktop_choice(request),
        "qr": svg(page, 180),
        "page_url": page,
    })


# ------------------------------------------------------- app updates

GITHUB_RELEASE = re.compile(r"github\.com/([^/]+)/([^/]+)/releases/")
BUILD_IN_TAG = re.compile(r"build(\d+)")
NOTES_LINE = re.compile(r"^What's new:\s*(.+)$", re.MULTILINE)


def _latest_from_github(apk_url):
    """The newest Android release on GitHub: its build number, version and
    notes, read from the release the workflow published
    (.github/workflows/android-app.yml). None if it can't be read."""
    import json
    import urllib.request

    match = GITHUB_RELEASE.search(apk_url or "")
    if not match:
        return None
    owner, repo = match.groups()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "DictionMasters"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            release = json.load(response)
    except Exception:
        return None
    build = BUILD_IN_TAG.search(release.get("tag_name", ""))
    if not build:
        return None
    version = re.search(r"android-([\w.]+)-build", release.get("tag_name", ""))
    notes = NOTES_LINE.search(release.get("body") or "")
    return {
        "build": int(build.group(1)),
        "version": version.group(1) if version else "",
        "notes": notes.group(1).strip() if notes else "",
    }


def latest_android_release():
    """What the newest Android app is. Set by hand with
    NATIVE_APP_ANDROID_LATEST_BUILD, or read from GitHub Releases (kept for
    15 minutes, so GitHub is asked at most a few times an hour)."""
    from django.core.cache import cache

    manual = int(getattr(settings, "NATIVE_APP_ANDROID_LATEST_BUILD", 0) or 0)
    if manual:
        return {"build": manual, "version": getattr(settings, "NATIVE_APP_ANDROID_LATEST_VERSION", ""),
                "notes": getattr(settings, "NATIVE_APP_ANDROID_UPDATE_NOTES", "")}
    apk = getattr(settings, "NATIVE_APP_ANDROID_APK_URL", "")
    if not apk:
        return None
    key = "native-app:latest-android"
    latest = cache.get(key)
    if latest is None:
        latest = _latest_from_github(apk) or {}
        cache.set(key, latest, 15 * 60 if latest else 5 * 60)
    return latest or None


def app_version(request):
    """/app/version.json — the newest app, so an installed app can offer to
    update itself (static/js/native_app.js, "Update available")."""
    latest = latest_android_release()
    android = None
    if latest and getattr(settings, "NATIVE_APP_ANDROID_APK_URL", ""):
        android = {
            **latest,
            "url": settings.NATIVE_APP_ANDROID_APK_URL,
            # Builds older than this must update before carrying on (0 = never forced).
            "min_build": int(getattr(settings, "NATIVE_APP_ANDROID_MIN_BUILD", 0) or 0),
        }
    response = JsonResponse({"android": android})
    response["Cache-Control"] = "no-cache"
    return response


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
