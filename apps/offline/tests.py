"""What a learner's app is told to keep, and when a page counts as changed."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.assembly_recitals.models import Recital, Section
from apps.billing.models import BillingSettings, Subscription
from apps.echospell.models import Activity, ActivityItem, CardLesson, Category, Group, Level
from apps.learning_modules.models import Day, LearningModule, Term, Week
from apps.learning_tools.models import ToolLevels

from .catalog import build, levels_for, manifest

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name="Ada", **extra)


class ManifestCase(TestCase):
    def setUp(self):
        self.addCleanup(cache.clear)
        cache.clear()
        self.one, _ = Level.objects.update_or_create(name="Level 1", defaults={"is_published": True})
        self.two, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        self.words = Category.objects.create(name="Offline words", slug="offline-words", kind="words")
        self.one.categories.add(self.words)
        self.group = Group.objects.create(level=self.one, number=71, slug="off-71")
        self.other = Group.objects.create(level=self.two, number=72, slug="off-72")
        self.card = CardLesson.objects.create(group=self.group, category=self.words, word="Goat")
        self.activity = Activity.objects.create(group=self.group, kind="word-search", title="Find")
        self.item = ActivityItem.objects.create(activity=self.activity, answer="goat")
        self.pupil = person("pupil@example.com", role="student", level="Level 1")

    def pages(self, user=None):
        cache.clear()
        return {page["p"]: page["v"] for page in manifest(user or self.pupil)["pages"]}


class WhatIsListedTests(ManifestCase):
    def test_a_learners_own_level_only(self):
        pages = self.pages()
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/", pages)
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/{self.words.slug}/", pages)
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/activities/{self.activity.slug}/", pages)
        self.assertNotIn(f"/echospell/{self.two.slug}/{self.other.slug}/", pages)

    def test_a_higher_level_lists_the_echospell_it_uses(self):
        pages = self.pages(person("g8@example.com", role="student", level="Level 8"))
        self.assertIn(f"/echospell/{self.two.slug}/{self.other.slug}/", pages)        # the nearest level written
        self.assertNotIn(f"/echospell/{self.one.slug}/{self.group.slug}/", pages)

    def test_modules_for_their_level_and_for_everyone(self):
        def module(name, levels):
            made = LearningModule.objects.create(name=name, levels=levels)
            term = Term.objects.create(module=made, name="First")
            week = Week.objects.create(term=term, number=1)
            Day.objects.create(week=week, day_name="monday")
            return made
        mine, everyone, theirs = module("Mine", ",Level 1,"), module("All", ""), module("Not", ",Level 2,")
        pages = self.pages()
        self.assertIn(f"/learning-modules/{mine.slug}/first/week-1/monday/", pages)
        self.assertIn(f"/learning-modules/{everyone.slug}/first/week-1/monday/", pages)
        self.assertFalse(any(path.startswith(f"/learning-modules/{theirs.slug}/") for path in pages))

    def test_recitals_are_listed_which_the_old_crawl_never_reached(self):
        section = Section.objects.create(name="Verses", slug="verses")
        Recital.objects.create(section=section, title="One", slug="one")
        Recital.objects.create(section=section, title="Hidden", slug="hidden", is_published=False)
        pages = self.pages()
        self.assertIn("/assembly-recitals/verses/", pages)
        self.assertIn("/assembly-recitals/verses/one/", pages)
        self.assertNotIn("/assembly-recitals/verses/hidden/", pages)

    def test_a_tool_their_grade_cant_open_is_left_out(self):
        ToolLevels.objects.update_or_create(tool="assembly_recitals:hub", defaults={"levels": ",Level 3,"})
        section = Section.objects.create(name="Verses", slug="verses")
        Recital.objects.create(section=section, title="One", slug="one")
        pages = self.pages()
        self.assertNotIn("/assembly-recitals/verses/", pages)
        self.assertNotIn("/assembly-recitals/", pages)

    def test_nothing_that_should_not_be_kept(self):
        for path in self.pages():
            self.assertFalse(path.startswith(("/manage/", "/billing/", "/school/", "/accounts/logout")), path)

    def test_someone_with_no_level_gets_the_shared_tools_not_every_level(self):
        loner = person("solo@example.com", role="individual")
        self.assertEqual(levels_for(loner), [])
        pages = self.pages(loner)
        self.assertIn("/accounts/dashboard/", pages)
        self.assertFalse(any(path.startswith(f"/echospell/{self.one.slug}/") for path in pages))
        self.assertEqual(levels_for(person("lv@example.com", role="individual", level="Level 2")), ["Level 2"])


class VersionTests(ManifestCase):
    def path(self):
        return f"/echospell/{self.one.slug}/{self.group.slug}/"

    def test_the_same_content_keeps_its_version(self):
        self.assertEqual(self.pages()[self.path()], self.pages()[self.path()])

    def test_changing_a_word_changes_the_groups_pages_and_no_others(self):
        recital_section = Section.objects.create(name="Verses", slug="verses")
        Recital.objects.create(section=recital_section, title="One", slug="one")
        before = self.pages()
        self.card.word = "Boat"
        self.card.save()
        after = self.pages()
        self.assertNotEqual(before[self.path()], after[self.path()])
        self.assertEqual(before["/assembly-recitals/verses/one/"], after["/assembly-recitals/verses/one/"])

    def test_changing_an_activitys_answer_changes_the_page(self):
        before = self.pages()
        self.item.answer = "boat"
        self.item.save()
        self.assertNotEqual(before[self.path()], self.pages()[self.path()])

    def test_front_pages_have_no_version_so_they_always_refresh(self):
        self.assertEqual(self.pages()["/accounts/dashboard/"], "")

    def test_a_level_is_read_once_however_many_learners_ask(self):
        cache.clear()
        manifest(self.pupil)
        twin = person("twin@example.com", role="student", level="Level 1")
        with CaptureQueriesContext(connection) as asked:
            manifest(twin)
        self.assertFalse([q for q in asked if "echospell_" in q["sql"]], "the level's list comes from the cache")


class SecurityTests(ManifestCase):
    url = "/offline-sync/manifest/"

    def test_signed_out_gets_nothing(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("echospell", response.content.decode())

    def test_the_list_is_private(self):
        self.client.force_login(self.pupil)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(response.json()["access"])

    def test_no_list_once_their_access_has_ended(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": True})
        Subscription.objects.update_or_create(user=self.pupil, defaults={"trial_ends_at": timezone.now() - timedelta(days=2)})
        self.assertEqual(manifest(self.pupil)["access"], False)
        self.assertEqual(manifest(self.pupil)["pages"], [])


class ReportTests(ManifestCase):
    def test_a_level_can_be_measured(self):
        shelf = build(["Level 1"], {"echospell:hub"})
        self.assertGreater(shelf.counts["EchoSpell"], 3)
