"""Listen and circle (circle every word heard), and a QR code for every
activity: on its page for the people who make the books, as a PNG, and on
the group's sheet of codes."""

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase

from .activity_kinds import get_kind
from .marking import feedback_for, given_answer, mark_response
from .models import Activity, ActivityAttempt, ActivityItem, Group, Level

User = get_user_model()


class ListenAndCircleTests(TestCase):
    def setUp(self):
        self.level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.group = Group.objects.create(level=self.level, number=8, slug="circle-8")
        self.activity = Activity.objects.create(group=self.group, kind="listen-and-circle", title="Circle them")
        self.item = ActivityItem.objects.create(activity=self.activity, answer="sheep\nShip",
                                                options="sheep\nship\nshop\nchip",
                                                audio_url="https://example.com/sheep-ship.mp3")
        self.pupil = User.objects.create_user("pupil@example.com", "pw-12345678", first_name="Ada",
                                              role="student", level="Level 2")
        self.client.force_login(self.pupil)
        self.url = f"/echospell/{self.level.slug}/{self.group.slug}/activities/{self.activity.slug}/"

    def test_right_only_when_exactly_the_words_said_are_circled(self):
        kind = get_kind("listen-and-circle")
        self.assertTrue(mark_response(kind, self.item, "ship, sheep"))
        self.assertTrue(mark_response(kind, self.item, "SHEEP, ship"))
        self.assertFalse(mark_response(kind, self.item, "sheep"))                 # one missed
        self.assertFalse(mark_response(kind, self.item, "sheep, ship, shop"))     # one too many
        self.assertFalse(mark_response(kind, self.item, ""))
        self.assertEqual(feedback_for(kind, self.item, "sheep", False), "The words to circle were sheep, Ship")

    def test_every_circled_word_is_sent(self):
        self.assertEqual(given_answer(QueryDict("item-5=sheep&item-5=ship"), 5), "sheep, ship")
        self.assertEqual(given_answer(QueryDict("item-5=+goat+"), 5), "goat")     # one answer, as before

    def test_the_learner_circles_and_is_marked(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'class="circle-row"')
        self.assertContains(page, f'type="checkbox" name="item-{self.item.pk}" value="shop"')
        self.assertNotContains(page, "data-qr")                                   # codes are for staff
        response = self.client.post(self.url, {f"item-{self.item.pk}": ["ship", "sheep"]})
        attempt = ActivityAttempt.objects.get(user=self.pupil)
        self.assertEqual(attempt.percent, 100)
        self.assertContains(self.client.get(response.url), "You circled: <strong>ship, sheep</strong>", html=False)


class ActivityQrTests(TestCase):
    def setUp(self):
        self.level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.group = Group.objects.create(level=self.level, number=9, slug="qr-9")
        self.activity = Activity.objects.create(group=self.group, kind="dictation", title="Spell it")
        ActivityItem.objects.create(activity=self.activity, answer="goat")
        self.staff = User.objects.create_user("staff@example.com", "pw-12345678", first_name="Sam", is_staff=True)
        self.client.force_login(self.staff)
        self.path = f"/echospell/{self.level.slug}/{self.group.slug}/activities/{self.activity.slug}/"

    def test_staff_see_the_activitys_code(self):
        page = self.client.get(self.path)
        self.assertContains(page, "Scan to open this activity")
        self.assertContains(page, f'data-qr-url="https://www.dictionmasters.app{self.path}"')
        self.assertContains(page, "<svg")
        self.assertContains(page, f'/echospell/{self.level.slug}/{self.group.slug}/qr-sheet/')

    def test_the_png(self):
        response = self.client.get("/echospell/qr.png", {"path": self.path, "name": "Level 2 - Group 9 - Spell it"})
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertIn("Level 2 - Group 9 - Spell it - QR code.png", response["Content-Disposition"])
        for bad in ("//evil.example/", "https://evil.example/", "/no-such-page-here/x/y/z/"):
            self.assertEqual(self.client.get("/echospell/qr.png", {"path": bad}).status_code, 404, bad)
        self.client.force_login(User.objects.create_user("t@example.com", "pw-12345678", first_name="Tola", role="teacher"))
        self.assertEqual(self.client.get("/echospell/qr.png", {"path": self.path}).status_code, 404)

    def test_the_groups_sheet_has_its_activities(self):
        page = self.client.get(f"/echospell/{self.level.slug}/{self.group.slug}/qr-sheet/")
        self.assertContains(page, "Activities")
        self.assertContains(page, "Spell it")
