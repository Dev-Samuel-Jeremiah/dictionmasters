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


DESKTOP_APP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/142.0.0.0 Safari/537.36 DictionMastersApp/desktop")
DESKTOP_RELEASES = "https://github.com/example/dictionmasters/releases/download/desktop"


class DesktopAppTests(TestCase):
    """The computer app for Windows, Mac and Linux (desktop/ project)."""

    def test_the_computer_app_is_recognised(self):
        response = self.client.get("/", HTTP_USER_AGENT=DESKTOP_APP)
        self.assertRedirects(response, "/app/welcome/", fetch_redirect_response=False)
        welcome = self.client.get("/app/welcome/", HTTP_USER_AGENT=DESKTOP_APP)
        self.assertContains(welcome, 'data-native-app="desktop"')

    def test_payments_stay_on_in_the_computer_app(self):
        # Not an app store: Paystack works there as on the website.
        response = self.client.get("/billing/plans/", HTTP_USER_AGENT=DESKTOP_APP)
        self.assertNotContains(response, "can't be bought in the app")

    @override_settings(NATIVE_APP_HIDE_PAYMENTS=["ios", "android", "desktop"])
    def test_payments_can_be_hidden_in_the_computer_app_too(self):
        response = self.client.get("/billing/plans/", HTTP_USER_AGENT=DESKTOP_APP)
        self.assertContains(response, "can't be bought in the app")

    @override_settings(NATIVE_APP_DESKTOP_DOWNLOAD_URL=DESKTOP_RELEASES + "/")
    def test_get_the_app_offers_the_installers(self):
        windows_chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142.0 Safari/537.36"
        page = self.client.get("/app/get/", HTTP_USER_AGENT=windows_chrome)
        self.assertEqual(page.context["computer"], "windows")
        self.assertContains(page, DESKTOP_RELEASES + "/DictionMasters-Setup.exe")
        self.assertContains(page, DESKTOP_RELEASES + "/DictionMasters-Setup-Windows7-8.exe")
        self.assertContains(page, DESKTOP_RELEASES + "/DictionMasters-mac-arm64.dmg")
        self.assertContains(page, DESKTOP_RELEASES + "/DictionMasters-linux-amd64.deb")

    @override_settings(NATIVE_APP_DESKTOP_DOWNLOAD_URL=DESKTOP_RELEASES)
    def test_the_big_button_picks_the_installer_for_this_computer(self):
        agents = {
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142.0 Safari/537.36": "DictionMasters-Setup.exe",
            "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 Chrome/109.0 Safari/537.36": "DictionMasters-Setup-Windows7-8.exe",
            "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/142.0 Safari/537.36": "DictionMasters-Setup-Windows7-8.exe",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15": "DictionMasters-mac-arm64.dmg",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:115.0) Gecko/20100101 Firefox/115.0": "DictionMasters-mac-legacy-x64.dmg",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0": "DictionMasters-linux-amd64.deb",
            "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0": "DictionMasters-linux-x86_64.AppImage",
        }
        for agent, file in agents.items():
            page = self.client.get("/app/get/", HTTP_USER_AGENT=agent)
            self.assertEqual(page.context["desktop_choice"]["url"], f"{DESKTOP_RELEASES}/{file}", agent)
            self.assertContains(page, "data-desktop-button")
            self.assertContains(page, 'id="desktop-choices"')                  # for desktop_download.js
            self.assertContains(page, "js/desktop_download.js")
        mac = self.client.get("/app/get/", HTTP_USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) Safari/605")
        self.assertContains(mac, 'Download for <span data-desktop-os>Mac</span>', html=False)
        self.assertContains(mac, "Get the app for Mac")                         # the footer too

    @override_settings(NATIVE_APP_DESKTOP_DOWNLOAD_URL=DESKTOP_RELEASES)
    def test_no_big_button_for_phones_and_chromebooks(self):
        for agent in ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 Chrome/142.0 Safari/537.36",
                      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/142.0 Mobile Safari/537.36"):
            page = self.client.get("/app/get/", HTTP_USER_AGENT=agent)
            self.assertIsNone(page.context["desktop_choice"], agent)
            self.assertNotContains(page, "data-desktop-button")
            self.assertNotContains(page, "Get the app for")
        chromebook = self.client.get("/app/get/", HTTP_USER_AGENT="Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) Chrome/142.0")
        self.assertContains(chromebook, "Install on this computer")             # it installs the website

    @override_settings(NATIVE_APP_DESKTOP_DOWNLOAD_URL="")
    def test_no_installers_until_published(self):
        page = self.client.get("/app/get/", HTTP_USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/605")
        self.assertEqual(page.context["computer"], "mac")
        self.assertNotContains(page, "DictionMasters-")
        self.assertContains(page, "Install on this computer")


class SignedInFooterTests(TestCase):
    @override_settings(NATIVE_APP_DESKTOP_DOWNLOAD_URL=DESKTOP_RELEASES)
    def test_the_signed_in_footer_names_the_computer_too(self):
        user = get_user_model().objects.create_user("ada@example.com", "mango-river-47", first_name="Ada", role="individual")
        self.client.force_login(user)
        agent = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
        page = self.client.get("/privacy/", HTTP_USER_AGENT=agent)
        self.assertContains(page, "Get the app for Linux", count=1)
        self.assertNotContains(page, "&#128241; Get the app")
