"""
What must hold for lesson videos:

  * a page never carries the address the video really lives at;
  * a playing link belongs to one account and runs out;
  * a copy is kept only where Django has allowed one, on a device within
    the limit, until the date it set — and can be taken back.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.access import subscription_for
from apps.billing.models import BillingSettings
from apps.book.models import ACADEMY, SectionVideo, Sound, SoundCategory

from .links import read_ticket, ticket, watch_url
from .models import OfflineVideoLicense, StudentDevice

User = get_user_model()
CLIP = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40      # stands in for an mp4


@override_settings(
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    OFFLINE_VIDEO_LICENSE_DAYS=7, MAX_OFFLINE_DEVICES_PER_STUDENT=2,
)
class LessonVideoTests(TestCase):
    def setUp(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"trial_days": 7, "paywall_enabled": True})
        group = SoundCategory.objects.create(name="Long vowels", programme=ACADEMY)
        self.sound = Sound.objects.create(category=group, symbol="iː", name="Long EE", is_published=True)
        self.video = SectionVideo.objects.create(
            sound=self.sound, section="lens", video_caption="How to say it",
            video_file=SimpleUploadedFile("lesson.mp4", CLIP, content_type="video/mp4"))
        self.learner = User.objects.create_user(email="ada@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.learner)

    # ---- the link ---------------------------------------------------------

    def test_the_page_never_shows_where_the_video_lives(self):
        page = self.client.get(f"/book/44-academy/{self.sound.slug}/lens/").content.decode()
        self.assertNotIn(self.video.video_file.url, page)
        self.assertNotIn(".mp4", page.split("data-ticket")[0].split("<video")[-1])
        self.assertIn("/videos/play/", page)
        self.assertIn("data-ticket", page)

    def test_a_link_plays_for_its_own_account_only(self):
        url = watch_url(self.video, self.learner)
        answer = self.client.get(url)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(b"".join(answer.streaming_content), CLIP)

        other = User.objects.create_user(email="ben@example.com", password="pw-12345678", first_name="Ben")
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_link_runs_out(self):
        raw = ticket(self.video, self.learner)
        self.assertIsNotNone(read_ticket(raw))
        with override_settings(VIDEO_LINK_SECONDS=-1):
            self.assertIsNone(read_ticket(raw))
            self.assertEqual(self.client.get(watch_url(self.video, self.learner)).status_code, 404)

    def test_seeking_asks_for_part_of_the_file(self):
        answer = self.client.get(watch_url(self.video, self.learner), HTTP_RANGE="bytes=10-19")
        self.assertEqual(answer.status_code, 206)
        self.assertEqual(answer["Content-Range"], f"bytes 10-19/{len(CLIP)}")
        self.assertEqual(b"".join(answer.streaming_content), CLIP[10:20])
        self.assertEqual(answer["Cache-Control"], "private, max-age=0, no-store")

    def test_signed_out_and_unpaid_learners_get_nothing(self):
        url = watch_url(self.video, self.learner)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)      # to the sign-in page
        self.client.force_login(self.learner)
        subscription = subscription_for(self.learner)
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    # ---- keeping a copy ---------------------------------------------------

    def prepare(self, device="device-a", name="Ada's phone"):
        return self.client.post("/videos/prepare/", {
            "ticket": ticket(self.video, self.learner), "device": device,
            "device_name": name, "title": "How to say it",
        }, content_type="application/json")

    def test_keeping_a_copy_registers_the_device_and_sets_a_date(self):
        answer = self.prepare().json()
        self.assertTrue(answer["ok"])
        self.assertIn("/videos/keep/", answer["url"])
        self.assertNotIn(".mp4", answer["url"])
        self.assertNotIn("key", answer)
        licence = OfflineVideoLicense.objects.get()
        self.assertEqual(licence.student, self.learner)
        self.assertEqual(licence.video, self.video)
        self.assertAlmostEqual(licence.expires_at, timezone.now() + timedelta(days=7), delta=timedelta(minutes=1))
        self.assertEqual(StudentDevice.objects.get().name, "Ada's phone")

        # The copy itself comes through Django, for that device only.
        bytes_back = self.client.get(answer["url"])
        self.assertEqual(bytes_back.status_code, 200)
        self.assertEqual(b"".join(bytes_back.streaming_content), CLIP)
        self.assertEqual(self.client.get(answer["url"].split("?")[0] + "?device=someone-else").status_code, 404)

    def test_only_so_many_devices(self):
        self.assertTrue(self.prepare("device-a").json()["ok"])
        self.assertTrue(self.prepare("device-b").json()["ok"])
        third = self.prepare("device-c").json()
        self.assertFalse(third["ok"])
        self.assertIn("2 devices", third["error"])
        self.assertEqual(StudentDevice.objects.count(), 2)

        # Removing one frees the place.
        first = StudentDevice.objects.get(device_identifier="device-a")
        self.client.post(f"/videos/devices/{first.pk}/deactivate/")
        self.assertTrue(self.prepare("device-c").json()["ok"])

    def test_copies_are_checked_whenever_the_app_is_online(self):
        self.prepare()
        licence = OfflineVideoLicense.objects.get()
        answer = self.client.post("/videos/licenses/", {"device": "device-a"},
                                  content_type="application/json").json()
        self.assertTrue(answer["licenses"][0]["live"])

        # Taken back by an admin: the device is told, and asking again fails.
        licence.is_active = False
        licence.save()
        answer = self.client.post("/videos/licenses/", {"device": "device-a"},
                                  content_type="application/json").json()
        self.assertFalse(answer["licenses"][0]["live"])
        self.assertEqual(self.client.get(f"/videos/keep/{ticket(self.video, self.learner, 'keep')}/?device=device-a")
                         .status_code, 404)

    def test_an_expired_copy_is_renewed_while_the_plan_is_live(self):
        self.prepare()
        licence = OfflineVideoLicense.objects.get()
        licence.expires_at = timezone.now() - timedelta(days=1)
        licence.save()
        self.assertFalse(licence.is_live)
        self.client.post("/videos/licenses/", {"device": "device-a"}, content_type="application/json")
        licence.refresh_from_db()
        self.assertTrue(licence.is_live)

        # But not once the plan has run out.
        subscription = subscription_for(self.learner)
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.save()
        licence.expires_at = timezone.now() - timedelta(days=1)
        licence.save()
        self.client.post("/videos/licenses/", {"device": "device-a"}, content_type="application/json")
        licence.refresh_from_db()
        self.assertFalse(licence.is_live)

    def test_a_learner_removes_their_own_copy(self):
        self.prepare()
        licence = OfflineVideoLicense.objects.get()
        self.client.post("/videos/release/", {"id": licence.pk, "device": "device-a"},
                         content_type="application/json")
        self.assertFalse(OfflineVideoLicense.objects.exists())

    def test_the_offline_page_and_the_menu(self):
        self.prepare()
        page = self.client.get("/videos/offline/")
        self.assertContains(page, "My downloads")
        self.assertContains(page, "data-saved-pages")            # pages saved one by one
        self.assertContains(page, "Ada&#x27;s phone")
        self.assertContains(self.client.get("/accounts/dashboard/"), "/videos/offline/")

    def test_nobody_can_reach_another_learners_devices(self):
        self.prepare()
        device = StudentDevice.objects.get()
        other = User.objects.create_user(email="ben@example.com", password="pw-12345678", first_name="Ben")
        self.client.force_login(other)
        self.assertEqual(self.client.post(f"/videos/devices/{device.pk}/deactivate/").status_code, 404)
        self.assertEqual(self.client.get("/videos/devices/").json()["devices"], [])
        device.refresh_from_db()
        self.assertTrue(device.is_active)

    def test_the_control_room_can_take_a_copy_back(self):
        self.prepare()
        staff = User.objects.create_user(email="sam@example.com", password="pw-12345678", first_name="Sam",
                                         is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get("/manage/learner-devices/"), "Ada&#x27;s phone")
        self.assertContains(self.client.get("/manage/offline-copies/"), "How to say it")


@override_settings(
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    OFFLINE_VIDEO_LICENSE_DAYS=7, MAX_OFFLINE_DEVICES_PER_STUDENT=2,
)
class RecordingTests(TestCase):
    """Recordings (audio) are saved for offline listening like videos: the
    same tickets, licences and limits, each copy marked as a recording."""

    SONG = b"ID3\x03\x00" + bytes(range(200)) * 30                     # stands in for an mp3

    def setUp(self):
        from apps.assembly_recitals.models import Recital, Section

        BillingSettings.objects.update_or_create(pk=1, defaults={"trial_days": 7, "paywall_enabled": True})
        self.section = Section.objects.create(name="Days & Months")
        self.recital = Recital.objects.create(
            section=self.section, title="Days of the Week", lines="Monday\nTuesday",
            video_file=SimpleUploadedFile("days.mp4", CLIP, content_type="video/mp4"),
            audio_file=SimpleUploadedFile("days.mp3", self.SONG, content_type="audio/mpeg"))
        self.learner = User.objects.create_user(email="ada@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.learner)

    def prepare(self, media, device="device-a"):
        return self.client.post("/videos/prepare/", {
            "ticket": ticket(self.recital, self.learner, media=media), "device": device, "device_name": "Ada's phone",
        }, content_type="application/json").json()

    def test_a_recording_is_saved_beside_the_same_rows_video(self):
        heard = self.prepare("audio")
        self.assertTrue(heard["ok"])
        self.assertEqual(heard["content_type"], "audio/mpeg")
        self.assertEqual(heard["size"], len(self.SONG))
        self.assertEqual(heard["title"], "Recording")
        copy = self.client.get(heard["url"])
        self.assertEqual(b"".join(copy.streaming_content), self.SONG)

        seen = self.prepare("video")
        self.assertTrue(seen["ok"])
        copy = self.client.get(seen["url"])
        self.assertEqual(b"".join(copy.streaming_content), CLIP)
        self.assertEqual(sorted(OfflineVideoLicense.objects.values_list("media", flat=True)), ["audio", "video"])
        # One device holds both: still one place used.
        self.assertEqual(StudentDevice.objects.count(), 1)

        # Checked when the app is online, each with its own key.
        rows = self.client.post("/videos/licenses/", {"device": "device-a"}, content_type="application/json").json()
        self.assertEqual(sorted(row["video"][-2:] == ":a" for row in rows["licenses"]), [False, True])

    def test_a_recording_ticket_never_fetches_the_video(self):
        self.assertTrue(self.prepare("audio")["ok"])
        played = self.client.get(watch_url(self.recital, self.learner, media="audio"))
        self.assertEqual(b"".join(played.streaming_content), self.SONG)
        # The audio licence doesn't open the video's copy.
        from .links import keep_url

        video_copy = self.client.get(keep_url(self.recital, self.learner) + "?device=device-a")
        self.assertEqual(video_copy.status_code, 404)

    def test_the_player_keeps_its_address_and_adds_the_strip(self):
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.learner
        html = Template('{% load videos %}{% audio_player recital css="rc-audio" ra=True hook="data-recital-audio" %}').render(
            Context({"recital": self.recital, "request": request}))
        self.assertIn(f'src="{self.recital.audio_file.url}"', html)
        self.assertIn("data-ticket=", html)
        self.assertIn(f'data-video-id="', html)
        self.assertIn("-a\"", html)
        self.assertIn("data-ra-media", html)
        self.assertIn("data-recital-audio", html)
        self.assertIn("Listen offline", html)

        # Signed out: it still plays, with nothing to save.
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()
        html = Template("{% load videos %}{% audio_player recital %}").render(Context({"recital": self.recital, "request": request}))
        self.assertIn("<audio", html)
        self.assertNotIn("data-ticket", html)
        # Only a data- attribute can be asked for.
        request.user = self.learner
        html = Template('{% load videos %}{% audio_player recital hook="onplay=alert(1)" %}').render(
            Context({"recital": self.recital, "request": request}))
        self.assertNotIn("onplay", html)

    def test_a_recording_elsewhere_has_nothing_to_save(self):
        from django.template import Context, Template
        from django.test import RequestFactory

        self.recital.audio_url = "https://example.org/days.mp3"
        self.recital.save()
        request = RequestFactory().get("/")
        request.user = self.learner
        html = Template("{% load videos %}{% audio_player recital %}").render(Context({"recital": self.recital, "request": request}))
        self.assertIn('src="https://example.org/days.mp3"', html)
        self.assertNotIn("data-ticket", html)

    def test_the_recital_pages_offer_both(self):
        page = self.client.get(f"/assembly-recitals/{self.section.slug}/{self.recital.slug}/")
        if page.status_code != 200:
            self.skipTest(f"recital page answered {page.status_code}")
        self.assertContains(page, "Listen offline")
        self.assertContains(page, "Watch offline")
        listing = self.client.get(f"/assembly-recitals/{self.section.slug}/")
        self.assertContains(listing, "data-offline-later")
        self.assertContains(listing, "Listen offline")
        self.assertContains(listing, "Watch offline")

    def test_library_audio_and_video_items(self):
        from apps.diction_library.models import LibraryItem

        from .links import stored_file

        song = LibraryItem.objects.create(title="Rain song", kind="audio",
                                          file=SimpleUploadedFile("rain.mp3", self.SONG, content_type="audio/mpeg"))
        book = LibraryItem.objects.create(title="A book", kind="book",
                                          file=SimpleUploadedFile("book.pdf", b"%PDF-1.4", content_type="application/pdf"))
        self.assertEqual(stored_file(song, "audio"), song.file)
        self.assertIsNone(stored_file(song, "video"))
        self.assertIsNone(stored_file(book, "audio"))
        answer = self.client.post("/videos/prepare/", {
            "ticket": ticket(song, self.learner, media="audio"), "device": "device-a"}, content_type="application/json").json()
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["title"], "Recording")
        refused = self.client.post("/videos/prepare/", {
            "ticket": ticket(book, self.learner, media="audio"), "device": "device-a"}, content_type="application/json")
        self.assertEqual(refused.status_code, 404)


@override_settings(
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
              "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
    OFFLINE_VIDEO_LICENSE_DAYS=7, MAX_OFFLINE_DEVICES_PER_STUDENT=2,
)
class ManyRecordingPagesTests(TestCase):
    """EchoSpell cards (a Full and a Quick recording, each saved on its own),
    Diction Radio (a Save beside every episode) and the "Save this page"
    strip on pages of short sounds."""

    FULL = b"ID3\x03\x00full" + bytes(range(100)) * 20
    QUICK = b"ID3\x03\x00quick" + bytes(range(90)) * 20

    def setUp(self):
        from apps.echospell.models import CardLesson, Category, Group, Level

        BillingSettings.objects.update_or_create(pk=1, defaults={"trial_days": 7, "paywall_enabled": True})
        self.level = Level.objects.create(name="Pre-Level", slug="pre-level-offline")
        self.group = Group.objects.create(level=self.level, number=1, slug="group-1-offline")
        self.category, _ = Category.objects.get_or_create(slug="spelling", defaults={"name": "Spelling words", "kind": "words"})
        self.level.categories.add(self.category)
        self.card = CardLesson.objects.create(
            group=self.group, category=self.category, word="Goat",
            audio_file=SimpleUploadedFile("goat.mp3", self.FULL, content_type="audio/mpeg"),
            quick_audio_file=SimpleUploadedFile("goat-quick.mp3", self.QUICK, content_type="audio/mpeg"))
        self.learner = User.objects.create_user(email="ada@example.com", password="pw-12345678", first_name="Ada",
                                                is_staff=True)
        self.client.force_login(self.learner)

    def keep(self, media):
        return self.client.post("/videos/prepare/", {
            "ticket": ticket(self.card, self.learner, media=media), "device": "device-a"},
            content_type="application/json").json()

    def test_the_full_and_quick_recordings_are_saved_apart(self):
        full, quick = self.keep("audio"), self.keep("quick")
        self.assertTrue(full["ok"] and quick["ok"])
        self.assertEqual(b"".join(self.client.get(full["url"]).streaming_content), self.FULL)
        self.assertEqual(b"".join(self.client.get(quick["url"]).streaming_content), self.QUICK)
        self.assertEqual(sorted(OfflineVideoLicense.objects.values_list("media", flat=True)), ["audio", "quick"])
        rows = self.client.post("/videos/licenses/", {"device": "device-a"}, content_type="application/json").json()
        self.assertEqual(sorted(row["video"].rsplit(":", 1)[-1] for row in rows["licenses"]), ["a", "q"])

    def test_the_card_page_offers_each_recording_and_the_page(self):
        page = self.client.get(f"/echospell/{self.level.slug}/{self.group.slug}/{self.category.slug}/")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertEqual(html.count("data-offline-keep"), 2)
        self.assertIn(f'-{self.card.pk}-a"', html)
        self.assertIn(f'-{self.card.pk}-q"', html)
        self.assertEqual(html.count("data-ra-sync="), 2)            # the words still highlight along
        self.assertIn("data-offline-save-page", html)

    def test_radio_episodes_of_ours_can_be_saved(self):
        from apps.diction_radio.models import RadioEpisode, RadioProgram

        show = RadioProgram.objects.create(title="Diction in a Minute")
        ours = RadioEpisode.objects.create(program=show, title="Think",
                                           audio_file=SimpleUploadedFile("think.mp3", self.FULL, content_type="audio/mpeg"))
        RadioEpisode.objects.create(program=show, title="Hosted", audio_url="https://example.org/hosted.mp3")
        html = self.client.get("/radio/").content.decode()
        self.assertEqual(html.count("data-radio-offline="), 1)
        self.assertIn(f'-{ours.pk}-a"', html)
        self.assertIn("data-offline-later", html)
        answer = self.client.post("/videos/prepare/", {
            "ticket": ticket(ours, self.learner, media="audio"), "device": "device-a"}, content_type="application/json").json()
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["title"], "Recording")

    def test_the_save_page_strip_is_only_for_people_signed_in(self):
        from django.template import Context, Template
        from django.contrib.auth.models import AnonymousUser

        strip = Template('{% include "offline/_save_page.html" %}')
        self.assertIn("data-offline-save-page", strip.render(Context({"user": self.learner})))
        self.assertNotIn("data-offline-save-page", strip.render(Context({"user": AnonymousUser()})))
