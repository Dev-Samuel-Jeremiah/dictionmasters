"""What a learner's app is told to keep, and when a page counts as changed."""

import base64
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

from .catalog import build, learner_secret, levels_for, manifest, plan_ends

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

    def test_the_app_is_told_when_their_plan_ends(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": True})
        ends = timezone.now() + timedelta(days=12)
        Subscription.objects.update_or_create(user=self.pupil, defaults={"trial_ends_at": ends})
        self.assertEqual(manifest(self.pupil)["access_ends"], int(ends.timestamp() * 1000))

    def test_a_schools_pupil_follows_the_schools_plan(self):
        from apps.schools.models import School

        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": True})
        school = School.objects.create(name="Unity", email="u@example.com")
        paid = timezone.now() + timedelta(days=40)
        Subscription.objects.create(school=school, paid_until=paid)
        pupil = person("schooled@example.com", role="student", level="Level 1", school=school)
        self.assertEqual(manifest(pupil)["access_ends"], int(paid.timestamp() * 1000))

    def test_no_end_date_when_nothing_ends(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": False})
        self.assertIsNone(manifest(self.pupil)["access_ends"])
        staff = person("staff@example.com", is_staff=True)
        self.assertIsNone(plan_ends(staff))

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

    @override_settings(STORAGE_CORS_READY=True)
    def test_only_videos_stored_here_are_listed(self):
        videos = manifest(self.pupil)["videos"]
        self.assertEqual(videos, [self.ref])                             # a video elsewhere can't be kept

    @override_settings(STORAGE_CORS_READY=False)
    def test_no_videos_or_stored_files_until_the_bucket_allows_it(self):
        found = manifest(self.pupil)
        self.assertEqual(found["videos"], [])
        self.assertFalse(found["storage_media"])

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

    @override_settings(STORAGE_CORS_READY=True)
    def test_or_comes_straight_from_storage_still_checked_here(self):
        device = StudentDevice.objects.create(student=self.pupil, device_identifier="d1")
        licence = self.licence(device)
        with patch("apps.videos.views.streaming.brief_link", return_value="https://r2.example/x"):
            response = self.keep(device)
            self.assertRedirects(response, "https://r2.example/x", fetch_redirect_response=False)
            self.assertIn("no-store", response["Cache-Control"])
            licence.delete()
            self.assertEqual(self.keep(device).status_code, 404)         # no licence, no link

    def test_a_saved_video_never_outlasts_the_plan(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"paywall_enabled": True})
        ends = timezone.now() + timedelta(days=5)
        Subscription.objects.update_or_create(user=self.pupil, defaults={"trial_ends_at": ends})
        device = StudentDevice.objects.create(student=self.pupil, device_identifier="d1")
        licence = self.licence(device)
        answer = self.client.post("/videos/licenses/", data={"device": "d1"}, content_type="application/json").json()
        licence.refresh_from_db()
        self.assertAlmostEqual(licence.expires_at, ends, delta=timedelta(seconds=1))
        self.assertEqual(answer["licenses"][0]["expires_at"], licence.expires_at.isoformat())
        Subscription.objects.filter(user=self.pupil).update(trial_ends_at=timezone.now() + timedelta(days=400))
        self.client.post("/videos/licenses/", data={"device": "d1"}, content_type="application/json")
        licence.refresh_from_db()                                       # a long plan: the usual 90 days
        self.assertAlmostEqual(licence.expires_at, timezone.now() + timedelta(days=90), delta=timedelta(minutes=1))

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


class LearnerTests(ManifestCase):
    def test_who_is_signed_in_with_their_key_and_a_fresh_token(self):
        self.client.force_login(self.pupil)
        answer = self.client.get("/offline-sync/learner/")
        self.assertIn("no-store", answer["Cache-Control"])
        found = answer.json()
        self.assertEqual(found["id"], self.pupil.pk)
        self.assertEqual(len(base64.b64decode(found["secret"])), 32)
        self.assertTrue(found["token"])
        self.assertEqual(manifest(self.pupil)["learner"], {"id": self.pupil.pk, "secret": found["secret"]})

    def test_each_learner_has_their_own_key_and_it_lasts(self):
        other = person("other@example.com", role="student", level="Level 1")
        self.assertNotEqual(learner_secret(self.pupil), learner_secret(other))
        self.pupil.set_password("a-new-password-9")                     # a password reset keeps it
        self.assertEqual(learner_secret(self.pupil), learner_secret(User.objects.get(pk=self.pupil.pk)))

    def test_signed_out_gets_nothing(self):
        self.assertEqual(self.client.get("/offline-sync/learner/").status_code, 401)

    def test_signed_in_pages_carry_the_learner(self):
        self.client.force_login(self.pupil)
        page = self.client.get("/accounts/dashboard/", follow=True).content.decode()
        self.assertIn(f'data-learner="{self.pupil.pk}"', page[:4000])          # where the app looks for it
        self.client.logout()
        self.assertNotIn("data-learner", self.client.get("/").content.decode())

    def sign_in(self, who, remember=True):
        fields = {"username": who.email, "password": "mango-river-47"}
        if remember:
            fields["remember_device"] = "1"
        self.client.post("/accounts/switch/add/")          # as on a shared device: "Add another account"
        self.client.post("/accounts/login/", fields)

    def test_who_may_sign_in_offline_on_this_device(self):
        """Remembered on the device's switcher, with no password needed:
        the app keeps their key for the offline sign-in screen."""
        self.pupil.first_name, self.pupil.last_name = "Ada", "Obi"
        self.pupil.save()
        self.sign_in(self.pupil)
        found = self.client.get("/offline-sync/learner/").json()
        self.assertEqual((found["name"], found["initials"], found["device"]), ("Ada Obi", "AO", [self.pupil.pk]))
        self.assertEqual(self.client.get("/offline-sync/manifest/").json()["learner"]["device"], [self.pupil.pk])
        # A second pupil, signed in without "Remember me": the first stays listed, they don't.
        other = person("other@example.com", role="student", level="Level 1")
        self.sign_in(other, remember=False)
        found = self.client.get("/offline-sync/learner/").json()
        self.assertEqual((found["id"], found["device"]), (other.pk, [self.pupil.pk]))

    def test_admins_may_but_changed_passwords_never_sign_in_offline(self):
        admin = person("admin@example.com", is_staff=True)
        self.sign_in(admin)
        self.assertEqual(self.client.get("/offline-sync/learner/").json()["device"], [admin.pk])
        self.client = self.client_class()                   # the pupil's own device
        self.sign_in(self.pupil)
        self.assertEqual(self.client.get("/offline-sync/learner/").json()["device"], [self.pupil.pk])
        self.pupil.set_password("a-new-password-9")       # changed on another device: asks for it again
        self.pupil.save()
        self.client.force_login(self.pupil)
        self.assertEqual(self.client.get("/offline-sync/learner/").json()["device"], [])

    def test_taken_off_the_device(self):
        self.sign_in(self.pupil)
        self.client.post("/accounts/switch/remove/", {"user": self.pupil.pk})
        self.assertEqual(self.client.get("/offline-sync/learner/").json()["device"], [])


class EverythingReachableTests(ManifestCase):
    def test_pages_a_learner_reaches_from_the_tools_are_listed(self):
        """Found by visiting every link offline: these opened online but
        weren't kept, so the app showed "You're offline" instead."""
        seen = build(["Level 1"], {"tricks:home"}).seen
        for path in ["/tricks/sections/", "/tricks/sections/lens/", "/tricks/sections/minimal-pairs/",
                     "/assessments/", "/assessments/results/", "/assessments/type/practice/"]:
            self.assertIn(path, seen)


class ChosenLevelsTests(ManifestCase):
    """Someone who can open every level chooses which to keep on a device."""

    def test_an_admin_keeps_the_levels_they_choose(self):
        admin = person("boss@example.com", is_staff=True)
        self.client.force_login(admin)
        bare = [page["p"] for page in self.client.get("/offline-sync/manifest/").json()["pages"]]
        self.assertFalse(any(p.startswith("/echospell/level-1/") for p in bare), "nothing chosen: shared tools only")
        chosen = [page["p"] for page in self.client.get("/offline-sync/manifest/?levels=Level 1,Nonsense").json()["pages"]]
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/", chosen)
        self.assertFalse(any(p.startswith(f"/echospell/{self.two.slug}/") for p in chosen))
        self.assertEqual(levels_for(admin, ["Level 1", "Level 2", "Level 3", "Level 4"]), ["Level 1", "Level 2", "Level 3"])

    def test_with_none_ticked_the_levels_they_work_in_are_kept(self):
        from apps.echospell.models import GroupStepsSeen

        admin = person("boss@example.com", is_staff=True)
        self.client.force_login(admin)
        self.assertIn('data-offline-levels="-"', self.client.get("/accounts/dashboard/", follow=True).content.decode()[:3000])
        GroupStepsSeen.objects.create(user=admin, group=self.group)       # they open a Level 1 card
        page = self.client.get("/accounts/dashboard/", follow=True).content.decode()
        self.assertIn('data-offline-levels="Level 1"', page[:3000], "the app hears of it, and downloads it")
        pages = [entry["p"] for entry in self.client.get("/offline-sync/manifest/").json()["pages"]]
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/", pages)
        self.assertContains(self.client.get("/videos/offline/"), "the levels you've been working in are kept: <strong>Level 1</strong>")
        # Ticking levels on the device wins.
        pages = [entry["p"] for entry in self.client.get("/offline-sync/manifest/?levels=Level 2").json()["pages"]]
        self.assertFalse(any(p.startswith(f"/echospell/{self.one.slug}/{self.group.slug}") for p in pages))
        # A pupil's page says nothing: their level decides.
        self.client.force_login(self.pupil)
        self.assertNotIn("data-offline-levels", self.client.get("/accounts/dashboard/", follow=True).content.decode()[:3000])

    def test_a_pupil_keeps_their_own_level_whatever_is_asked(self):
        self.client.force_login(self.pupil)
        pages = [page["p"] for page in self.client.get("/offline-sync/manifest/?levels=Level 2").json()["pages"]]
        self.assertIn(f"/echospell/{self.one.slug}/{self.group.slug}/", pages)
        self.assertFalse(any(p.startswith(f"/echospell/{self.two.slug}/") for p in pages))

    def test_the_offline_page_offers_the_choice_only_to_those_who_have_one(self):
        self.client.force_login(person("boss@example.com", is_staff=True))
        self.assertContains(self.client.get("/videos/offline/"), "Levels to keep on this device")
        self.client.force_login(self.pupil)
        self.assertNotContains(self.client.get("/videos/offline/"), "Levels to keep on this device")


class ReportTests(ManifestCase):
    def test_a_level_can_be_measured(self):
        shelf = build(["Level 1"], {"echospell:hub"})
        self.assertGreater(shelf.counts["EchoSpell"], 3)
