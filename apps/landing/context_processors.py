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
    ("learn", ("/scheme/weeks/",)),
    ("practice", ("/scheme/practise/",)),
    ("practice", ("/daily-practice/", "/assessments/", "/clash/", "/tutor/")),
    ("learn", (
        "/learning-tools/", "/lesson-audio/", "/book/", "/tricks/", "/echospell/", "/learning-modules/",
        "/reading-club/", "/assembly-recitals/", "/conversational-dialogue/", "/reference-library/", "/library/", "/radio/", "/quick-words/",
    )),
    ("me", ("/billing/", "/videos/offline/", "/accounts/grown-ups/")),
    ("home", ("/accounts/dashboard/", "/school/dashboard/", "/school/class/", "/scheme/")),
)


# The home pages: everywhere else gets a Back button (templates/base.html).
HOME_PATHS = {"/", "/accounts/dashboard/", "/school/dashboard/"}


def nav(request):
    """`nav_section` in every template: the main tab the current page sits
    under; and `show_back`: whether the page gets the Back button."""
    path = getattr(request, "path", "") or ""
    show_back = path not in HOME_PATHS
    for section, prefixes in NAV_SECTIONS:
        if path.startswith(prefixes):
            return {"nav_section": section, "show_back": show_back}
    return {"nav_section": "", "show_back": show_back}
