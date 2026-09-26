"""
Diction Masters as an app you can install (a Progressive Web App).

  /manifest.webmanifest  what the installed app is called, its icons and colours
  /sw.js                 the service worker, at the top of the site so it
                         looks after every page
  /offline/              what shows when there is no connection

Keeping the installed app up to date is the point of how the service
worker is built (templates/pwa/sw.js). Pages are tried from the server first
and successful learner pages are kept on this browser for offline study.
Account-entry, billing and staff pages are excluded. Logging out clears the
learner page and media caches and queued progress so another learner on a
shared device cannot see the previous learner's offline data. Static files
(stylesheets, scripts, pictures) are kept the same way as before, and their
addresses change whenever they do, so nothing old is ever shown there.

The worker carries a version made from those files; when a release
changes any of them, the browser sees a new worker, and the page offers
the update (static/js/pwa.js).
"""

import hashlib
import json
import mimetypes
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

NAME = "Diction Masters"
NAVY = "#14213D"
PARCHMENT = "#F2F5FC"

_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "ico": "image/x-icon",
}


def _uploaded_icon():
    """Return the configured brand image and a cache-busting version."""
    from apps.landing.models import SiteBranding

    branding = SiteBranding.load()
    upload = branding.logo or branding.favicon
    if not upload:
        return None
    try:
        # Accessing .name is safe even when a FileField has no file.
        name = upload.name
    except ValueError:
        return None
    if not name:
        return None
    updated = getattr(branding, "updated_at", None)
    version = str(int(updated.timestamp())) if updated else name
    return upload, version


def _icons():
    """Install icons made from the uploaded brand artwork when available."""
    configured = _uploaded_icon()
    if configured:
        _, version = configured
        icons = []
        for size in (192, 512):
            icons.append({
                "src": f"{reverse('pwa_icon', args=[size, 'any'])}?v={version}",
                "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any",
            })
        for size in (192, 512):
            icons.append({
                "src": f"{reverse('pwa_icon', args=[size, 'maskable'])}?v={version}",
                "sizes": f"{size}x{size}", "type": "image/png", "purpose": "maskable",
            })
        return icons
    return [
        {"src": static("pwa/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": static("pwa/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": static("pwa/maskable-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
        {"src": static("pwa/maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]


def app_icon(request, size, purpose="any"):
    """Make a correctly sized PNG install icon from the site's uploaded logo."""
    from io import BytesIO
    from PIL import Image, ImageOps
    from apps.landing.models import SiteBranding

    if size not in {180, 192, 512} or purpose not in {"any", "maskable"}:
        return HttpResponse(status=404)
    branding = SiteBranding.load()
    upload = branding.logo or branding.favicon
    if not upload:
        return HttpResponse(status=404)
    try:
        upload.open("rb")
        with Image.open(upload) as original:
            source = ImageOps.exif_transpose(original).convert("RGBA")
            source.load()
    except (OSError, ValueError):
        return HttpResponse(status=404)
    finally:
        upload.close()

    # Keep the full logo visible on a square app tile. Maskable icons get a
    # wider safe margin so launchers can crop their corners without clipping it.
    margin = 0.20 if purpose == "maskable" else 0.08
    inner = int(size * (1 - margin * 2))
    source.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (244, 239, 226, 255))
    canvas.alpha_composite(source, ((size - source.width) // 2, (size - source.height) // 2))
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    response = HttpResponse(output.getvalue(), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def brand_asset(request, kind):
    """Serve the public uploaded logo or favicon through this origin."""
    from apps.landing.models import SiteBranding

    if kind not in {"logo", "favicon"}:
        return HttpResponse(status=404)
    upload = getattr(SiteBranding.load(), kind)
    if not upload:
        return HttpResponse(status=404)
    try:
        handle = upload.open("rb")
    except (OSError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(handle, content_type=mimetypes.guess_type(upload.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


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


@cache_control(max_age=60, public=True)
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
        "theme_color": "#1846E0",
        "categories": ["education"],
        "icons": _icons(),
        "shortcuts": [
            {"name": "My dashboard", "url": "/accounts/dashboard/"},
            {"name": "EchoSpell", "url": "/echospell/"},
            {"name": "Tricks to Sound Fluent", "url": "/tricks/"},
        ],
    }, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


# Never cached: the browser must see a new worker as soon as there is one.
@cache_control(no_cache=True, no_store=True, must_revalidate=True, max_age=0)
def service_worker(request):
    precache = ["/offline/", static("pwa/icon-192.png"), static("css/base.css"), static("css/ui.css"), static("css/theme.css")]
    from apps.landing.models import SiteBranding

    branding = SiteBranding.load()
    version = str(int(branding.updated_at.timestamp())) if branding.updated_at else ""
    for kind in ("logo", "favicon"):
        if getattr(branding, kind):
            precache.append(f"{reverse('pwa_brand_asset', args=[kind])}?v={version}")
    body = render(request, "pwa/sw.js", {
        "version": app_version(),
        "offline_url": "/offline/",
        "static_prefix": "/" + settings.STATIC_URL.strip("/") + "/",
        "precache": json.dumps(precache + [static("js/offline_pages.js"), static("js/offline_video.js"),
                                           static("js/offline_sync.js")]),
        # Where lesson pictures and audio live besides this site, so they can be kept offline.
        "media_hosts": json.dumps(list(getattr(settings, "OFFLINE_MEDIA_HOSTS", []))),
    }).content
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    from apps.landing.models import SiteBranding

    return render(request, "pwa/offline.html", {"branding": SiteBranding.load()})