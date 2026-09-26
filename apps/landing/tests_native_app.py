"""The Android and iPhone apps (apps/landing/native_app.py).

    python manage.py test apps.landing.tests_native_app
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

ANDROID = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 DictionMastersApp/android"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 DictionMastersApp/ios"
BROWSER = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36"


class NativeAppTests(TestCase):
    def test_a_browser_still_gets_the_marketing_home_page(self):
        response = self.client.get("/", HTTP_USER_AGENT=BROWSER)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-native-app")
        self.assertNotContains(response, "native_app.js")

    def test_the_app_opens_on_its_welcome_screen(self):
        response = self.client.get("/", HTTP_USER_AGENT=ANDROID)
        self.assertRedirects(response, "/app/welcome/", fetch_redirect_response=False)
        welcome = self.client.get("/app/welcome/", HTTP_USER_AGENT=ANDROID)
        self.assertEqual(welcome.status_code, 200)
        self.assertContains(welcome, 'data-native-app="android"')
        self.assertContains(welcome, "native_app.js")
        self.assertNotContains(welcome, "data-install-fab")

    def test_a_signed_in_learner_opens_on_the_dashboard(self):
        user = get_user_model().objects.create_user("learner@example.com", "a-long-password-123", first_name="Ada")
        self.client.force_login(user)
        response = self.client.get("/", HTTP_USER_AGENT=IPHONE)
        self.assertRedirects(response, "/accounts/dashboard/", fetch_redirect_response=False)

    def test_buying_pages_are_replaced_in_the_app(self):
        response = self.client.get("/billing/plans/", HTTP_USER_AGENT=IPHONE)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "can't be bought in the app")
        self.assertNotContains(response, "Paystack")

    @override_settings(NATIVE_APP_HIDE_PAYMENTS=["ios"])
    def test_payments_can_be_allowed_on_android_only(self):
        response = self.client.get("/billing/plans/", HTTP_USER_AGENT=ANDROID)
        self.assertNotContains(response, "can't be bought in the app")

    def test_browsers_still_see_the_plans(self):
        response = self.client.get("/billing/plans/", HTTP_USER_AGENT=BROWSER)
        self.assertNotContains(response, "can't be bought in the app")

    @override_settings(NATIVE_APP_ANDROID_PACKAGE="app.dictionmasters.mobile", NATIVE_APP_ANDROID_SHA256=["AA:BB"])
    def test_android_deep_link_file(self):
        data = self.client.get("/.well-known/assetlinks.json").json()
        self.assertEqual(data[0]["target"]["package_name"], "app.dictionmasters.mobile")
        self.assertEqual(data[0]["target"]["sha256_cert_fingerprints"], ["AA:BB"])

    @override_settings(NATIVE_APP_IOS_TEAM_ID="ABCDE12345", NATIVE_APP_IOS_BUNDLE_ID="app.dictionmasters.mobile")
    def test_iphone_deep_link_file(self):
        data = self.client.get("/.well-known/apple-app-site-association").json()
        self.assertEqual(data["applinks"]["details"][0]["appIDs"], ["ABCDE12345.app.dictionmasters.mobile"])


class StoreRequirementsTests(TestCase):
    """Both app stores need a privacy policy and in-app account deletion."""

    def test_privacy_policy_is_public(self):
        self.assertContains(self.client.get("/privacy/"), "Privacy policy")

    def test_a_learner_can_delete_their_account(self):
        User = get_user_model()
        user = User.objects.create_user("gone@example.com", "a-long-password-123", first_name="Ada")
        self.client.force_login(user)
        wrong = self.client.post("/accounts/delete/", {"password": "nope"})
        self.assertContains(wrong, "isn&#x27;t right")
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        response = self.client.post("/accounts/delete/", {"password": "a-long-password-123"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("storage", response["Clear-Site-Data"])
        self.assertFalse(User.objects.filter(pk=user.pk).exists())


APK = "https://github.com/example/dictionmasters/releases/latest/download/diction-masters.apk"


class GetTheAppTests(TestCase):
    """/app/get/ and the "Get the app" links (apps/landing/native_app.py)."""

    @override_settings(NATIVE_APP_ANDROID_APK_URL=APK)
    def test_android_phones_get_the_download(self):
        page = self.client.get("/app/get/", HTTP_USER_AGENT=BROWSER)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["device"], "android")
        self.assertContains(page, APK)
        self.assertContains(page, "Download the Android app")
        self.assertContains(page, "data-android-app")  # install buttons lead here

    @override_settings(NATIVE_APP_ANDROID_APK_URL="", NATIVE_APP_IOS_STORE_URL="")
    def test_iphones_get_add_to_home_screen_steps(self):
        iphone_safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
        page = self.client.get("/app/get/", HTTP_USER_AGENT=iphone_safari)
        self.assertEqual(page.context["device"], "ios")
        self.assertContains(page, "Add to Home Screen")
        self.assertNotContains(page, "Download the Android app")

    def test_computers_get_a_qr_code(self):
        page = self.client.get("/app/get/", HTTP_USER_AGENT="Mozilla/5.0 (X11; Linux x86_64) Chrome/130")
        self.assertEqual(page.context["device"], "desktop")
        self.assertContains(page, "<svg")

    @override_settings(NATIVE_APP_ANDROID_APK_URL=APK)
    def test_hidden_inside_the_app(self):
        self.assertRedirects(self.client.get("/app/get/", HTTP_USER_AGENT=ANDROID),
                             "/accounts/dashboard/", fetch_redirect_response=False)
        welcome = self.client.get("/app/welcome/", HTTP_USER_AGENT=ANDROID)
        self.assertNotContains(welcome, "Get the app")
        self.assertNotContains(welcome, "data-android-app")

    def test_the_footer_links_to_it_in_browsers(self):
        self.assertContains(self.client.get("/", HTTP_USER_AGENT=BROWSER), "/app/get/")


class UpdateAvailableTests(TestCase):
    """/app/version.json tells the installed app about a newer version."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    @override_settings(NATIVE_APP_ANDROID_APK_URL=APK, NATIVE_APP_ANDROID_LATEST_BUILD=7,
                       NATIVE_APP_ANDROID_LATEST_VERSION="1.1.0", NATIVE_APP_ANDROID_UPDATE_NOTES="New icon.",
                       NATIVE_APP_ANDROID_MIN_BUILD=3)
    def test_the_newest_version_set_by_hand(self):
        data = self.client.get("/app/version.json", HTTP_USER_AGENT=ANDROID).json()
        self.assertEqual(data["android"], {"build": 7, "version": "1.1.0", "notes": "New icon.",
                                           "url": APK, "min_build": 3})

    @override_settings(NATIVE_APP_ANDROID_APK_URL="", NATIVE_APP_ANDROID_LATEST_BUILD=0)
    def test_nothing_to_offer_without_a_download(self):
        self.assertIsNone(self.client.get("/app/version.json").json()["android"])

    @override_settings(NATIVE_APP_ANDROID_APK_URL=APK, NATIVE_APP_ANDROID_LATEST_BUILD=0)
    def test_reads_the_newest_github_release(self):
        import io
        import json
        from unittest import mock

        release = {"tag_name": "android-1.0.0-build12",
                   "body": "What's new: Faster lessons.\n\nDiction Masters for Android..."}
        fake = mock.MagicMock()
        fake.__enter__.return_value = io.BytesIO(json.dumps(release).encode())
        with mock.patch("urllib.request.urlopen", return_value=fake) as opened:
            data = self.client.get("/app/version.json").json()["android"]
            self.client.get("/app/version.json")  # second time comes from the cache
        self.assertEqual(opened.call_count, 1)
        self.assertIn("api.github.com/repos/example/dictionmasters/releases/latest", opened.call_args[0][0].full_url)
        self.assertEqual((data["build"], data["version"], data["notes"]), (12, "1.0.0", "Faster lessons."))

    @override_settings(NATIVE_APP_ANDROID_APK_URL=APK, NATIVE_APP_ANDROID_LATEST_BUILD=0)
    def test_github_unreachable_means_no_update_offered(self):
        from unittest import mock

        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(self.client.get("/app/version.json").json()["android"])


class StaySignedInTests(TestCase):
    def test_the_app_keeps_people_signed_in(self):
        user = get_user_model().objects.create_user("stay@example.com", "a-long-password-123", first_name="Ada")
        self.client.force_login(user)
        self.client.get("/accounts/dashboard/", HTTP_USER_AGENT=ANDROID)
        self.assertGreater(self.client.session.get_expiry_age(), 150 * 24 * 60 * 60)

    def test_browsers_keep_the_normal_session(self):
        from django.conf import settings as dj

        user = get_user_model().objects.create_user("web@example.com", "a-long-password-123", first_name="Ada")
        self.client.force_login(user)
        self.client.get("/accounts/dashboard/", HTTP_USER_AGENT=BROWSER)
        self.assertEqual(self.client.session.get_expiry_age(), dj.SESSION_COOKIE_AGE)
