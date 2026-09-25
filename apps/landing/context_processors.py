from django.conf import settings
from django.utils.functional import SimpleLazyObject


def branding(request):
    """`branding` in every template: the uploaded logo and favicon.
    Looked up only on pages that actually use it."""

    def load():
        from .models import SiteBranding
        return SiteBranding.load()

    return {"branding": SimpleLazyObject(load), "site_url": settings.SITE_URL}


# Which main tab (Home, Learn, Practice, Progress, Me) a page belongs to,
# so the sidebar and the bottom tab bar can light the right one.
NAV_SECTIONS = (
    ("progress", ("/assessments/results/",)),
    ("practice", ("/daily-practice/", "/assessments/", "/clash/", "/tutor/")),
    ("learn", (
        "/learning-tools/", "/book/", "/tricks/", "/echospell/", "/learning-modules/",
        "/reading-club/", "/reference-library/", "/library/", "/radio/", "/quick-words/",
    )),
    ("me", ("/billing/", "/videos/offline/")),
    ("home", ("/accounts/dashboard/", "/school/dashboard/")),
)


def nav(request):
    """`nav_section` in every template: the main tab the current page sits under."""
    path = getattr(request, "path", "") or ""
    for section, prefixes in NAV_SECTIONS:
        if path.startswith(prefixes):
            return {"nav_section": section}
    return {"nav_section": ""}
