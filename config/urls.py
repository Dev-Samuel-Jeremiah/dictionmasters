"""
Root URL configuration for Diction Masters.

Each app owns its own urls.py; this file only wires apps together
under their mount point, so the routing table stays readable as the
product grows section by section.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.landing import native_app, pwa

urlpatterns = [
    path("manage/", include("apps.manage.urls")),
    path("admin/console/", include("apps.console.urls")),
    path("admin/", admin.site.urls),
    # Installing Diction Masters as an app (apps/landing/pwa.py).
    path("manifest.webmanifest", pwa.manifest, name="pwa_manifest"),
    path("pwa/icons/<int:size>/<str:purpose>.png", pwa.app_icon, name="pwa_icon"),
    path("site-branding/<str:kind>/", pwa.brand_asset, name="pwa_brand_asset"),
    path("sw.js", pwa.service_worker, name="pwa_worker"),
    path("offline/", pwa.offline, name="pwa_offline"),
    # The Android and iPhone apps (apps/landing/native_app.py).
    path("app/welcome/", native_app.welcome, name="native_app_welcome"),
    path(".well-known/assetlinks.json", native_app.android_asset_links, name="native_app_assetlinks"),
    path(".well-known/apple-app-site-association", native_app.apple_app_site_association, name="native_app_aasa"),
    path("", include("apps.landing.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("school/", include("apps.schools.urls")),
    path("learning-tools/", include("apps.learning_tools.urls")),
    path("search/", include("apps.platform_search.urls")),
    path("videos/", include("apps.videos.urls")),
    path("book/", include("apps.book.urls")),
    path("tricks/", include("apps.tricks.urls")),
    path("reference-library/", include("apps.reference_library.urls")),
    path("library/", include("apps.diction_library.urls")),
    path("radio/", include("apps.diction_radio.urls")),
    path("daily-practice/", include("apps.daily_practice.urls")),
    path("learning-modules/", include("apps.learning_modules.urls")),
    path("reading-club/", include("apps.reading_club.urls")),
    path("echospell/", include("apps.echospell.urls")),
    path("quick-words/", include("apps.quick_words.urls")),
    path("tutor/", include("apps.tutor.urls")),
    path("assessments/", include("apps.assessments.urls")),
    path("clash/", include("apps.clash.urls")),
    path("billing/", include("apps.billing.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
