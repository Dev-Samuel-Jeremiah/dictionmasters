from django.test import TestCase


class InstallableAppTests(TestCase):
    """Diction Masters installs as an app, and the app keeps itself up to date."""

    def test_the_manifest_describes_the_app(self):
        from django.contrib.staticfiles import finders

        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "Diction Masters")
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(data["start_url"].startswith("/accounts/dashboard/"))
        sizes = {(icon["sizes"], icon["purpose"]) for icon in data["icons"]}
        self.assertIn(("512x512", "maskable"), sizes)
        self.assertIn(("192x192", "any"), sizes)
        for icon in data["icons"]:
            name = icon["src"].split("/static/", 1)[1].split("?")[0]
            self.assertTrue(finders.find(name), name)

    def test_the_service_worker_is_never_cached_and_carries_a_version(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertIn("no-cache", response["Cache-Control"])
        body = response.content.decode()
        self.assertRegex(body, r'const VERSION = "[0-9a-f]{12}"')
        self.assertIn('const OFFLINE_URL = "/offline/"', body)
        # Pages come from the server, never from storage.
        self.assertIn('request.mode === "navigate"', body)

    def test_a_changed_file_means_a_new_version(self):
        import os
        import time
        from pathlib import Path

        from django.conf import settings

        from apps.landing import pwa

        before = pwa.app_version()
        target = Path(settings.STATICFILES_DIRS[0]) / "js" / "pwa.js"
        stamp = target.stat()
        try:
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 5_000_000_000))
            self.assertNotEqual(pwa.app_version(), before)
        finally:
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(pwa.app_version(), before)

    def test_the_offline_page(self):
        self.assertContains(self.client.get("/offline/"), "You're offline")

    def test_pages_link_the_app_and_the_dashboard_offers_to_install_it(self):
        from django.contrib.auth import get_user_model

        home = self.client.get("/")
        self.assertContains(home, 'rel="manifest" href="/manifest.webmanifest"')
        self.assertContains(home, "js/pwa.js")
        self.client.force_login(get_user_model().objects.create_user(
            email="app@example.com", password="pw-12345678", first_name="Ada"))
        dashboard = self.client.get("/accounts/dashboard/")
        self.assertContains(dashboard, "data-install-app")
        self.assertContains(dashboard, "Install the app")
        self.assertContains(dashboard, 'id="install-steps"')
