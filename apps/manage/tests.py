from django.contrib.auth import get_user_model
from django.test import TestCase

from .registry import screens

User = get_user_model()


class EveryPageOpensTests(TestCase):
    """Every page of the control room opens for an admin: the fixed pages,
    and each screen's list and add form."""

    def setUp(self):
        self.client.force_login(User.objects.create_user(
            email="admin@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))

    def test_the_fixed_pages(self):
        for url in ("/manage/", "/manage/branding/", "/manage/billing-settings/", "/manage/read-along/",
                    "/manage/echospell-import/", "/manage/search/?q=a"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_every_screen(self):
        for key, screen in screens().items():
            self.assertEqual(self.client.get(f"/manage/{key}/").status_code, 200, key)
            if not screen.get("readonly"):
                self.assertEqual(self.client.get(f"/manage/{key}/new/").status_code, 200, f"{key} add form")
