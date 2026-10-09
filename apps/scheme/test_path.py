"""An individual learner's scheme, at their own pace (apps/scheme/path.py):
they choose a level's scheme, see the next lesson and a Lessons card, and
move around its terms, weeks and days freely. Learn stays open to them."""

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
        self.assertContains(page, "Level 2 scheme · First Term, Week 1")
        self.assertContains(page, "EchoSpell Group 1")
        self.assertContains(page, 'href="/scheme/lessons/" class="px-card sh-weeks-card"')
        self.assertNotContains(page, "My weeks")
        self.assertContains(page, 'href="/accounts/grown-ups/"')

    def test_everything_is_open_and_the_next_lesson_follows_the_order(self):
        self.choose()
        # Any lesson, any week, any term opens.
        self.assertRedirects(self.client.get(f"/scheme/go/{self.e_g3.pk}/"), "/echospell/level-2/p3/",
                             fetch_redirect_response=False)
        self.assertEqual(path(self.solo, "Level 2")["next"]["title"], "EchoSpell Group 1")
        GroupProgress.objects.create(user=self.solo, group=self.g1)
        SchemeOpened.objects.create(user=self.solo, entry=self.e_story)
        state = path(self.solo, "Level 2")
        self.assertEqual((state["current"]["term"], state["current"]["week"]), (1, 2))
        self.assertEqual(state["next"]["title"], "EchoSpell Group 2")

    def test_lessons_lay_out_term_week_and_day(self):
        self.choose()
        GroupProgress.objects.create(user=self.solo, group=self.g1)
        page = self.client.get("/scheme/lessons/")
        self.assertContains(page, "Level 2 scheme · 1 of 4 done")
        self.assertContains(page, "First Term <small>1/3</small>", html=False)
        self.assertContains(page, "Second Term <small>0/1</small>", html=False)
        self.assertContains(page, "Week 1 · You're here")
        self.assertContains(page, "Monday")
        self.assertContains(page, "Tuesday")
        self.assertContains(page, "The Fox")
        second = self.client.get("/scheme/lessons/?term=2")
        self.assertContains(second, "EchoSpell Group 3")
        self.assertNotContains(second, "The Fox")
        # The old My weeks address now leads here.
        self.assertRedirects(self.client.get("/scheme/weeks/"), "/scheme/lessons/", fetch_redirect_response=False)

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
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/staff_home.html")
        self.client.force_login(child)
        self.assertTemplateUsed(self.client.get("/accounts/dashboard/"), "accounts/learner_home.html")
        for other in (staff, make("teach@example.com", role="teacher", level="Level 2")):
            self.client.force_login(other)
            self.assertRedirects(self.client.get("/scheme/choose/"), "/accounts/dashboard/",
                                 fetch_redirect_response=False)
