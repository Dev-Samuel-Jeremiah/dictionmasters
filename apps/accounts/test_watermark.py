"""The name watermark over signed-in pages (templatetags/watermark.py)."""

from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class WatermarkTests(TestCase):
    def test_signed_in_pages_carry_the_learners_name(self):
        ada = User.objects.create_user("ada@example.com", "mango-river-47", first_name="Ada", last_name="Obi",
                                       username="ada.obi", role="individual")
        self.client.force_login(ada)
        page = self.client.get("/accounts/dashboard/", follow=True).content.decode()
        self.assertIn('class="dm-watermark"', page)
        self.assertIn("Ada Obi · ada.obi · ", unquote(page))

    def test_not_for_visitors_or_the_control_room(self):
        self.assertNotIn('class="dm-watermark"', self.client.get("/").content.decode())
        staff = User.objects.create_user("staff@example.com", "mango-river-47", first_name="Sam", is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get("/manage/", follow=True), 'class="dm-watermark"')

    def test_a_name_cant_break_the_page(self):
        odd = User.objects.create_user("odd@example.com", "mango-river-47", first_name='<b>"Bo"</b>', role="individual")
        self.client.force_login(odd)
        page = unquote(self.client.get("/accounts/dashboard/", follow=True).content.decode())
        self.assertNotIn('<b>"Bo"', page.split('class="dm-watermark"')[1])
        self.assertIn("&lt;b&gt;&quot;Bo&quot;", page)
