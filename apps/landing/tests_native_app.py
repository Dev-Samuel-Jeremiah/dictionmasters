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
