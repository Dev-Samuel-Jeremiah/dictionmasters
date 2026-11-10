"""The Meta Pixel: only on the doors adults come in by, never near children
(apps/landing/meta_pixel.py)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()
PIXEL = "1458390994020652"
MARK = 'id="dm-meta-pixel"'


@override_settings(META_PIXEL_ID=PIXEL)
class MetaPixelTests(TestCase):
    def page(self, path, **extra):
        return self.client.get(path, follow=True, **extra).content.decode()

    def test_the_public_doors_carry_it_with_the_consent_banner(self):
        for path in ["/", "/welcome/", "/accounts/register/school/", "/accounts/register/individual/"]:
            html = self.page(path)
            self.assertIn(f'data-pixel="{PIXEL}"', html, path)
            self.assertIn("data-consent", html, path)
            self.assertNotIn("connect.facebook.net", html, "nothing from Meta in the page itself: only after Accept")

    def test_never_where_children_are(self):
        for path in ["/accounts/register/student/", "/accounts/join/", "/accounts/login/", "/privacy/"]:
            self.assertNotIn(MARK, self.page(path), path)
        pupil = User.objects.create_user("p@example.com", "pw-12345678", first_name="Ada", role="student", level="Level 1")
        self.client.force_login(pupil)
        for path in ["/", "/accounts/dashboard/", "/welcome/"]:
            self.assertNotIn(MARK, self.page(path), path)

    def test_never_in_the_apps(self):
        for agent in ["Mozilla/5.0 DictionMastersApp/android", "Mozilla/5.0 DictionMastersApp/desktop"]:
            self.assertNotIn(MARK, self.page("/", HTTP_USER_AGENT=agent), agent)

    def test_an_adult_signing_up_sends_one_event(self):
        self.client.post("/accounts/register/individual/", {
            "first_name": "Chioma", "last_name": "Obi", "email": "chioma@example.com",
            "password1": "River-gate-77", "password2": "River-gate-77", "start": "trial", "qualification": "graduate",
        })
        self.assertTrue(User.objects.filter(email="chioma@example.com").exists())
        first = self.page("/accounts/dashboard/")
        self.assertIn('data-event="CompleteRegistration"', first)
        self.assertNotIn("data-consent", first, "no banner on a signed-in page: only with consent given before")
        self.assertNotIn(MARK, self.page("/accounts/dashboard/"), "once")

    def test_the_privacy_page_lets_people_change_their_choice(self):
        html = self.page("/privacy/")
        self.assertIn('id="ads"', html)
        self.assertIn('data-ads-choice="no"', html)

    @override_settings(META_PIXEL_ID="")
    def test_switched_off_without_an_id(self):
        self.assertNotIn(MARK, self.page("/"))
