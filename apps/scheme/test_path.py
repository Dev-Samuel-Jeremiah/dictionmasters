"""An individual learner's scheme, at their own pace (apps/scheme/path.py):
they choose a level's scheme, see the next lesson and My weeks, and a week
opens when the one before it is done. Learn stays open to them."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.assessments.models import Assessment, Attempt
from apps.diction_library.models import LibraryItem
from apps.echospell.models import Group, GroupProgress, Level

from .models import SchemeChoice, SchemeEntry, SchemeOpened
from .path import path
from .tests import make

User = get_user_model()


class PathTests(TestCase):
    def setUp(self):
        Group.objects.all().delete()
        level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.g1, self.g2, self.g3 = [Group.objects.create(level=level, number=n, slug=f"p{n}") for n in (1, 2, 3)]
        self.story = LibraryItem.objects.create(title="The Fox", slug="the-fox")
        add = lambda term, week, day, **kw: SchemeEntry.objects.create(level="Level 2", term=term, week=week, day=day, **kw)
        self.e_g1 = add(1, 1, "monday", kind="group", group=self.g1)
        self.e_story = add(1, 1, "tuesday", kind="library", library_item=self.story)
        self.e_g2 = add(1, 2, "monday", kind="group", group=self.g2)
        self.e_g3 = add(2, 1, "monday", kind="group", group=self.g3)
        add(1, 3, "monday", kind="daily_practice", is_draft=True)                # a draft: never part of it
        self.solo = make("solo@example.com")
        self.client.force_login(self.solo)

    def choose(self, level="Level 2"):
        return self.client.post("/scheme/choose/", {"level": level})

    def test_with_no_scheme_chosen_the_dashboard_is_the_choice(self):
        page = self.client.get("/accounts/dashboard/")
        self.assertTemplateUsed(page, "scheme/choose.html")
        self.assertContains(page, "Choose your scheme")
        self.assertContains(page, "3 weeks · 4 lessons")
        self.assertContains(page, "Not sure where to start?")

    def test_the_placement_test_suggests_a_level(self):
        test = Assessment.objects.create(title="Placement", kind="placement")
        Attempt.objects.create(user=self.solo, assessment=test, status="marked", recommended_level="Level 2",
                               submitted_at=timezone.now())
        page = self.client.get("/scheme/choose/")
        self.assertContains(page, "Suggested for you")
        self.assertNotContains(page, "Not sure where to start?")

    def test_choosing_starts_at_week_one(self):
        self.assertRedirects(self.choose(), "/accounts/dashboard/", fetch_redirect_response=False)
        page = self.client.get("/accounts/dashboard/")
        self.assertTemplateUsed(page, "scheme/path_home.html")
        self.assertContains(page, "Level 2 scheme · Week 1 of 3")
        self.assertContains(page, "EchoSpell Group 1")
        self.assertContains(page, 'href="/scheme/weeks/" class="px-card sh-weeks-card"')
        self.assertContains(page, 'href="/accounts/grown-ups/"')

    def test_the_next_week_opens_when_this_one_is_done(self):
        self.choose()
        self.assertEqual(path(self.solo, "Level 2")["current"]["week"], 1)
        self.assertEqual(self.client.get(f"/scheme/go/{self.e_g2.pk}/").status_code, 404)       # not open yet
        GroupProgress.objects.create(user=self.solo, group=self.g1)
        self.assertEqual(path(self.solo, "Level 2")["current"]["week"], 1)                    # The Fox still to do
        self.assertRedirects(self.client.get(f"/scheme/go/{self.e_story.pk}/"), "/library/the-fox/",
                             fetch_redirect_response=False)
        state = path(self.solo, "Level 2")
        self.assertEqual((state["current"]["term"], state["current"]["week"]), (1, 2))
        self.assertEqual(state["next"]["title"], "EchoSpell Group 2")
        weeks = self.client.get("/scheme/weeks/")
        self.assertContains(weeks, "First Term, Week 2 · This week")
        self.assertContains(weeks, "First Term, Week 1")
        self.assertNotContains(weeks, "Second Term")
        self.assertEqual(self.client.get("/scheme/weeks/2/1/").status_code, 404)

    def test_all_done(self):
        self.choose()
        for group in (self.g1, self.g2, self.g3):
            GroupProgress.objects.create(user=self.solo, group=group)
        SchemeOpened.objects.create(user=self.solo, entry=self.e_story)
        self.assertContains(self.client.get("/accounts/dashboard/"), "finished the Level 2 scheme")

    def test_changing_scheme_keeps_what_was_done(self):
        level, _ = Level.objects.update_or_create(name="Level 5", defaults={"is_published": True})
        SchemeEntry.objects.create(level="Level 5", term=1, week=1, day="monday", kind="group",
                                   group=Group.objects.create(level=level, number=1, slug="five"))
        self.choose()
        GroupProgress.objects.create(user=self.solo, group=self.g1)
        SchemeOpened.objects.create(user=self.solo, entry=self.e_story)
        self.choose("Level 5")
        self.assertEqual(SchemeChoice.objects.get(user=self.solo).level, "Level 5")
        self.choose("Level 2")
        self.assertEqual(path(self.solo, "Level 2")["current"]["week"], 2)

    def test_learn_stays_open(self):
        self.choose()
        self.assertEqual(self.client.get("/learning-tools/").status_code, 200)
        self.assertEqual(self.client.get("/echospell/level-2/p3/").status_code, 200)

    def test_others_are_unchanged(self):
        staff = make("staff@example.com", is_staff=True)
        child = make("child@example.com", simple_home=True)
        self.client.force_login(staff)
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/dashboard.html")
        self.client.force_login(child)
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/learner_home.html")
        for other in (staff, make("teach@example.com", role="teacher", level="Level 2")):
            self.client.force_login(other)
            self.assertRedirects(self.client.get("/scheme/choose/"), "/accounts/dashboard/",
                                 fetch_redirect_response=False)
