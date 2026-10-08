"""A Learning Modules day as a guided lesson (Phase 2): one lesson item per
screen, and a day earned by opening every item."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Day, DayProgress, LearningModule, LessonItem, Term, Week

User = get_user_model()


class GuidedDayTests(TestCase):
    def setUp(self):
        LearningModule.objects.all().delete()
        self.module = LearningModule.objects.create(name="Sound Discovery", slug="sound-discovery")
        self.term = Term.objects.create(module=self.module, name="First Term")
        self.week = Week.objects.create(term=self.term, number=1)
        self.monday = Day.objects.create(week=self.week, day_name="monday")
        self.tuesday = Day.objects.create(week=self.week, day_name="tuesday")
        self.items = [LessonItem.objects.create(day=self.monday, title=title, order=n)
                      for n, title in enumerate(["Meet the sound", "Say it", "Sing it"])]
        LessonItem.objects.create(day=self.monday, title="Hidden", is_published=False, order=9)
        LessonItem.objects.create(day=self.tuesday, title="Tuesday's lesson")
        self.week2 = Week.objects.create(term=self.term, number=2)
        Day.objects.create(week=self.week2, day_name="monday")

        self.pupil = User.objects.create_user("pupil@example.com", "pw-12345678", first_name="Ada",
                                              role="student", level="Level 1")
        self.client.force_login(self.pupil)
        self.url = "/learning-modules/sound-discovery/first-term/week-1/monday/"

    def done(self, day=None):
        return DayProgress.objects.filter(user=self.pupil, day=day or self.monday).exists()

    def test_one_item_per_screen_starting_with_the_first(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Meet the sound")
        self.assertNotContains(page, "Say it</p>")
        self.assertContains(page, "Step 1 of 3")
        self.assertContains(page, f'href="{self.url}?step=2" class="lp-bar__next"')
        self.assertNotContains(page, "Hidden")
        self.assertNotContains(page, "Mark day complete")

    def test_the_day_is_earned_once_every_item_is_opened(self):
        self.client.get(self.url)
        self.client.get(self.url + "?step=3")
        self.assertFalse(self.done())
        # With no step, the page goes to the item not yet seen.
        page = self.client.get(self.url)
        self.assertContains(page, "Step 2 of 3")
        self.assertTrue(self.done())
        finish = self.client.get(self.url + "?step=finish")
        self.assertContains(finish, "Monday complete!")
        self.assertContains(finish, "/week-1/tuesday/")

    def test_a_finished_day_opens_on_its_finish_screen(self):
        for n in (1, 2, 3):
            self.client.get(f"{self.url}?step={n}")
        self.assertContains(self.client.get(self.url), "Monday complete!")

    def test_ticking_off_by_hand_no_longer_completes_a_day(self):
        response = self.client.post(self.url + "complete/", follow=True)
        self.assertFalse(self.done())
        self.assertContains(response, "completed by going through every one")

    def test_the_next_week_stays_locked_until_this_one_is_done(self):
        locked = "/learning-modules/sound-discovery/first-term/week-2/monday/"
        self.assertRedirects(self.client.get(locked), "/learning-modules/sound-discovery/first-term/",
                             fetch_redirect_response=False)
        for n in (1, 2, 3):
            self.client.get(f"{self.url}?step={n}")
        self.client.get("/learning-modules/sound-discovery/first-term/week-1/tuesday/")
        self.assertTrue(self.done(self.tuesday))
        self.assertEqual(self.client.get(locked).status_code, 200)

    def test_a_step_out_of_range_shows_the_next_item(self):
        self.assertContains(self.client.get(self.url + "?step=99"), "Step 1 of 3")
