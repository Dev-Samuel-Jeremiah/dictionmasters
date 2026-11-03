"""What a learner's app is told to keep, and when a page counts as changed."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.assembly_recitals.models import Recital, Section
from apps.billing.models import BillingSettings, Subscription
from apps.echospell.models import Activity, ActivityItem, CardLesson, Category, Group, Level
from apps.learning_modules.models import Day, LearningModule, Term, Week
from apps.learning_tools.models import ToolLevels
from apps.videos import links
from apps.videos.models import OfflineVideoLicense, StudentDevice

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

    def test_the_app_is_told_how_long_it_may_stay_offline(self):
        self.assertEqual(manifest(self.pupil)["offline_days"], 90)
        with self.settings(OFFLINE_ACCESS_DAYS=30):
            self.assertEqual(manifest(self.pupil)["offline_days"], 30)

    def test_no_list_once_their_access_has_ended(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": True})
        Subscription.objects.update_or_create(user=self.pupil, defaults={"trial_ends_at": timezone.now() - timedelta(days=2)})
        self.assertEqual(manifest(self.pupil)["access"], False)
        self.assertEqual(manifest(self.pupil)["pages"], [])
        self.assertEqual(manifest(self.pupil)["offline_days"], 0)              # the app closes its lessons


class VideoTests(ManifestCase):
    def setUp(self):
        super().setUp()
        section = Section.objects.create(name="Verses", slug="verses")
        self.kept = Recital.objects.create(section=section, title="Psalm", slug="psalm", video_file="book/videos/psalm.mp4",
                                           video_caption="The psalm")
        self.linked = Recital.objects.create(section=section, title="Linked", slug="linked", video_url="https://example.com/v.mp4")
        self.ref = f"{ContentType.objects.get_for_model(Recital).pk}-{self.kept.pk}"
        self.client.force_login(self.pupil)

    def test_only_videos_stored_here_are_listed(self):
        videos = manifest(self.pupil)["videos"]
        self.assertEqual(videos, [self.ref])                             # a video elsewhere can't be kept

    def test_a_fresh_ticket_for_a_video_on_their_list(self):
        answer = self.client.get(f"/offline-sync/video/{self.ref}/").json()
        self.assertEqual(answer["title"], "The psalm")
        found = links.read_ticket(answer["ticket"], links.WATCH)
        self.assertEqual((found["o"], found["u"]), (self.kept.pk, self.pupil.pk))

    def test_no_ticket_for_anything_else(self):
        ToolLevels.objects.update_or_create(tool="assembly_recitals:hub", defaults={"levels": ",Level 3,"})
        cache.clear()
        self.assertEqual(self.client.get(f"/offline-sync/video/{self.ref}/").status_code, 404)  # not for their grade
        self.assertEqual(self.client.get("/offline-sync/video/nonsense/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(f"/offline-sync/video/{self.ref}/").status_code, 401)

    def licence(self, device, video=None):
        return OfflineVideoLicense.objects.create(student=self.pupil, device=device, video=video or self.kept, title="v",
                                                  expires_at=OfflineVideoLicense.new_expiry())

    def keep(self, device):
        return self.client.get(f"{links.keep_url(self.kept, self.pupil)}?device={device.device_identifier}")

    def test_a_saved_video_passes_through_here_unless_told_otherwise(self):
        device = StudentDevice.objects.create(student=self.pupil, device_identifier="d1")
        self.licence(device)
        with patch("apps.videos.streaming.brief_link", return_value="https://r2.example/x"), \
             patch("apps.videos.views.streaming.serve", return_value=HttpResponse("bytes")) as served:
            self.assertEqual(self.keep(device).content, b"bytes")
            served.assert_called_once()

    @override_settings(VIDEO_KEEP_DIRECT=True)
    def test_or_comes_straight_from_storage_still_checked_here(self):
        device = StudentDevice.objects.create(student=self.pupil, device_identifier="d1")
        licence = self.licence(device)
        with patch("apps.videos.views.streaming.brief_link", return_value="https://r2.example/x"):
            response = self.keep(device)
            self.assertRedirects(response, "https://r2.example/x", fetch_redirect_response=False)
            self.assertIn("no-store", response["Cache-Control"])
            licence.delete()
            self.assertEqual(self.keep(device).status_code, 404)         # no licence, no link

    def test_checking_many_saved_videos_takes_no_more_queries_than_one(self):
        device = StudentDevice.objects.create(student=self.pupil, device_identifier="d1")
        self.licence(device)
        def asked():
            with CaptureQueriesContext(connection) as queries:
                answer = self.client.post("/videos/licenses/", data={"device": "d1"}, content_type="application/json").json()
            return len(queries), answer
        self.client.post("/videos/licenses/", data={"device": "d1"}, content_type="application/json")   # trial, once
        few, _ = asked()
        section = Section.objects.first()
        for number in range(6):
            self.licence(device, Recital.objects.create(section=section, title=f"V{number}", slug=f"v{number}"))
        many, answer = asked()
        self.assertEqual(many, few)
        self.assertEqual(len(answer["licenses"]), 7)
        self.assertTrue(all(row["live"] for row in answer["licenses"]))


class ReportTests(ManifestCase):
    def test_a_level_can_be_measured(self):
        shelf = build(["Level 1"], {"echospell:hub"})
        self.assertGreater(shelf.counts["EchoSpell"], 3)
