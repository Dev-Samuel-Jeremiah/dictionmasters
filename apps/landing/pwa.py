"""
Diction Masters as an app you can install (a Progressive Web App).

  /manifest.webmanifest  what the installed app is called, its icons and colours
  /sw.js                 the service worker, at the top of the site so it
                         looks after every page
  /offline/              what shows when there is no connection

Keeping the installed app up to date is the point of how the service
worker is built (templates/pwa/sw.js). Pages always come from the server,
so a new feature is there the moment it is released. Only the site's own
stylesheets, scripts and pictures are kept on the device, and their
addresses change whenever they do, so nothing old is ever shown.

The worker carries a version made from those files; when a release
changes any of them, the browser sees a new worker, and the page offers
the update (static/js/pwa.js). Nothing a learner has written is ever
stored on the device.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

NAME = "Diction Masters"
NAVY = "#14213D"
PARCHMENT = "#F4EFE2"


@lru_cache(maxsize=1)
def _released_version():
    """In production: a fingerprint of this release's static files, the
    same in every worker process, and new whenever any file changes."""
    listing = Path(settings.STATIC_ROOT) / "staticfiles.json"
    if listing.exists():
        return hashlib.sha256(listing.read_bytes()).hexdigest()[:12]
    return ""


def _working_version():
    """In development: a fingerprint of the files as they are right now."""
    digest = hashlib.sha256()
    for folder in settings.STATICFILES_DIRS:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file():
                digest.update(f"{path}:{path.stat().st_mtime_ns}".encode())
    return digest.hexdigest()[:12]


def app_version():
    worker = (Path(settings.BASE_DIR) / "templates" / "pwa" / "sw.js").read_bytes()
    files = _released_version() or _working_version()
    return hashlib.sha256(worker + files.encode()).hexdigest()[:12]


@cache_control(max_age=3600, public=True)
def manifest(request):
    return JsonResponse({
        "name": NAME,
        "short_name": NAME,
        "description": "Your private British English tutor: spelling, sounds, fluency and live reading practice.",
        "id": "/",
        "start_url": "/accounts/dashboard/?source=app",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": PARCHMENT,
        "theme_color": NAVY,
        "categories": ["education"],
        "icons": [
            {"src": static("pwa/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("pwa/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("pwa/maskable-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": static("pwa/maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "My dashboard", "url": "/accounts/dashboard/"},
            {"name": "EchoSpell", "url": "/echospell/"},
            {"name": "Tricks to Sound Fluent", "url": "/tricks/"},
        ],
    }, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


# Never cached: the browser must see a new worker as soon as there is one.
@cache_control(no_cache=True, no_store=True, must_revalidate=True, max_age=0)
def service_worker(request):
    body = render(request, "pwa/sw.js", {
        "version": app_version(),
        "offline_url": "/offline/",
        "static_prefix": "/" + settings.STATIC_URL.strip("/") + "/",
        "precache": json.dumps(["/offline/", static("pwa/icon-192.png"), static("css/base.css"), static("css/ui.css")]),
    }).content
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "pwa/offline.html")
