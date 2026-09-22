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
        self.assertContains(page, "Offline videos")
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
