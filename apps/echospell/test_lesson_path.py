"""An EchoSpell group as a guided lesson (Phase 2): the steps in order, a
group earned only by doing every step, and no more ticking it off by hand."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .lesson_path import lesson_path
from .models import Activity, ActivityItem, CardLesson, Category, Group, GroupProgress, Level

User = get_user_model()


class GuidedGroupTests(TestCase):
    def setUp(self):
        self.level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.group = Group.objects.create(level=self.level, number=7, slug="guided-7")
        self.words = Category.objects.create(name="Guided words", kind="words", order=1)
        self.empty = Category.objects.create(name="Guided empty", kind="words", order=2)
        self.level.categories.set([self.words, self.empty])
        CardLesson.objects.create(group=self.group, category=self.words, word="Goat")
        self.spell = Activity.objects.create(group=self.group, kind="dictation", title="Spell it", pass_mark=100, order=1)
        ActivityItem.objects.create(activity=self.spell, prompt="", answer="goat")
        self.read = Activity.objects.create(group=self.group, kind="read-aloud", title="Read it", pass_mark=50, order=2)
        ActivityItem.objects.create(activity=self.read, prompt="A goat")
        # An activity with no questions yet is not a step.
        Activity.objects.create(group=self.group, kind="dictation", title="Not ready", order=3)

        self.pupil = User.objects.create_user("pupil@example.com", "pw-12345678", first_name="Ada",
                                              role="student", level="Level 2")
        self.client.force_login(self.pupil)
        self.base = f"/echospell/{self.level.slug}/{self.group.slug}/"

    def path(self):
        return lesson_path(self.pupil, self.level, self.group)

    def done(self):
        return GroupProgress.objects.filter(user=self.pupil, group=self.group).exists()

    def test_the_steps_are_cards_with_something_in_them_then_activities_with_questions(self):
        steps = self.path()["steps"]
        self.assertEqual([(s["kind"], s["title"]) for s in steps],
                         [("card", "Guided words"), ("activity", "Spell it"), ("activity", "Read it")])
        self.assertEqual([s["number"] for s in steps], [1, 2, 3])

    def test_the_group_page_starts_the_lesson_with_one_button(self):
        page = self.client.get(self.base)
        self.assertContains(page, "data-lesson-go", count=1)
        self.assertContains(page, f'href="{self.base}{self.words.slug}/" class="lp-go"')
        self.assertContains(page, "0 of 3 steps done")
        self.assertNotContains(page, "Mark group complete")

    def test_the_group_is_earned_only_when_every_step_is_done(self):
        self.client.get(f"{self.base}{self.words.slug}/")
        self.assertTrue(self.path()["steps"][0]["done"])
        self.assertFalse(self.done())

        # Failing an activity doesn't count.
        self.client.post(f"{self.base}activities/{self.spell.slug}/", {f"item-{self.spell.items.get().pk}": "gote"})
        self.assertFalse(self.path()["steps"][1]["done"])
        self.client.post(f"{self.base}activities/{self.spell.slug}/", {f"item-{self.spell.items.get().pk}": "goat"})
        self.assertTrue(self.path()["steps"][1]["done"])
        self.assertFalse(self.done())

        # A recording counts once it has been sent; the teacher marks it later.
        self.client.post(f"{self.base}activities/{self.read.slug}/", {})
        self.assertTrue(self.done())
        page = self.client.get(self.base)
        self.assertContains(page, "Group 7 complete!")

    def test_the_bar_on_a_card_points_next_to_the_next_unfinished_step(self):
        page = self.client.get(f"{self.base}{self.words.slug}/")
        self.assertContains(page, "Step 1 of 3")
        self.assertContains(page, f'href="{self.base}activities/{self.spell.slug}/" class="lp-bar__next"')

    def test_a_card_type_with_nothing_in_it_keeps_its_old_buttons(self):
        page = self.client.get(f"{self.base}{self.empty.slug}/")
        self.assertNotContains(page, "data-lesson-bar")
        self.assertContains(page, "tab-steps")

    def test_the_result_page_moves_on_after_an_activity(self):
        response = self.client.post(f"{self.base}activities/{self.spell.slug}/",
                                    {f"item-{self.spell.items.get().pk}": "goat"}, follow=True)
        self.assertContains(response, "Step 2 of 3")
        # Next is the next unfinished step after this one, wrapping round
        # to the unopened card only once those are done.
        self.assertContains(response, f'href="{self.base}activities/{self.read.slug}/" class="lp-bar__next"')
        response = self.client.post(f"{self.base}activities/{self.read.slug}/", {}, follow=True)
        self.assertContains(response, f'href="{self.base}{self.words.slug}/" class="lp-bar__next"')

    def test_ticking_off_by_hand_no_longer_completes_a_group(self):
        response = self.client.post(f"{self.base}complete/", follow=True)
        self.assertFalse(self.done())
        self.assertContains(response, "completed by doing every step")

    def test_a_group_with_nothing_in_it_yet_is_done_once_opened(self):
        empty = Group.objects.create(level=self.level, number=8, slug="guided-8")
        self.client.get(f"/echospell/{self.level.slug}/{empty.slug}/")
        self.assertTrue(GroupProgress.objects.filter(user=self.pupil, group=empty).exists())

    def test_another_levels_group_stays_shut(self):
        other, _ = Level.objects.update_or_create(name="Level 9", defaults={"is_published": True})
        group = Group.objects.create(level=other, number=1, slug="guided-other")
        self.assertEqual(self.client.get(f"/echospell/{other.slug}/{group.slug}/").status_code, 403)
