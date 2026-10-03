"""Scan & Listen's saved readings. Nothing here reaches ElevenLabs."""

import json
from unittest import mock

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.book.models import ReadAlongTiming
from apps.schools.models import School

from . import scan_library
from .models import ScanReading

STORAGE = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
           "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
VOICE = (b"ID3audio", [["The", 0.0, 0.2], ["market", 0.25, 0.7]], 0.9)


@override_settings(STORAGES=STORAGE, SCAN_LISTEN_SYNC=True, ELEVENLABS_API_KEY="k", ELEVENLABS_VOICE_ID="v")
class SavedReadingTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity School", email="unity@example.com")
        self.teacher = self.user("teacher", "teacher", self.school)
        self.student = self.user("student", "student", self.school)
        self.client.force_login(self.teacher)

    def user(self, name, role, school=None):
        return User.objects.create_user(f"{name}@example.com", "pw-12345678", first_name=name.title(), role=role, school=school)

    def save(self, text, id="", title=""):
        response = self.client.post("/learning-tools/book-scanner/readings/save/",
                                    json.dumps({"text": text, "id": id, "title": title}), content_type="application/json")
        return response.json()

    def test_a_teachers_reading_is_saved_to_their_school(self):
        saved = self.save("The market at dawn.\n\nAdaeze woke early.")
        reading = ScanReading.objects.get(pk=saved["id"])
        self.assertEqual((reading.school, reading.owner, reading.title), (self.school, self.teacher, "The market at dawn."))
        self.assertEqual(saved["where"], "Unity School library")
        # Typing more updates the same reading.
        again = self.save("The market at dawn.\n\nAdaeze woke very early.", id=saved["id"])
        self.assertEqual((again["id"], ScanReading.objects.count()), (saved["id"], 1))

    def test_others_at_the_school_find_readings_with_audio_but_not_drafts(self):
        draft = ScanReading.objects.create(owner=self.teacher, school=self.school, title="Draft", text="A draft page")
        ready = ScanReading.objects.create(owner=self.teacher, school=self.school, title="Ready", text="A ready page",
                                           audio_status="ready", audio_file="scan_listen/x.mp3")
        self.client.force_login(self.student)
        found = [r["id"] for r in self.client.get("/learning-tools/book-scanner/readings/search/?q=page").json()["results"]]
        self.assertEqual(found, [ready.pk])
        self.assertNotIn(draft.pk, found)

    def test_other_schools_and_individuals_cannot_see_a_schools_readings(self):
        reading = ScanReading.objects.create(owner=self.teacher, school=self.school, title="Ours", text="Ours",
                                             audio_status="ready", audio_file="scan_listen/x.mp3")
        elsewhere = self.user("other", "teacher", School.objects.create(name="Elsewhere", email="e@example.com"))
        loner = self.user("loner", "individual")
        for person in (elsewhere, loner):
            self.client.force_login(person)
            self.assertEqual(self.client.get("/learning-tools/book-scanner/readings/search/").json()["results"], [])
            self.assertEqual(self.client.get(f"/learning-tools/book-scanner/readings/{reading.pk}/status/").status_code, 404)

    def test_an_individuals_readings_are_their_own(self):
        loner = self.user("loner", "individual")
        self.client.force_login(loner)
        saved = self.save("My own page.")
        self.assertIsNone(ScanReading.objects.get(pk=saved["id"]).school)
        self.assertEqual(saved["where"], "My readings")

    @mock.patch("apps.diction_library.narration.read_chapter", return_value=VOICE)
    def test_audio_is_made_once_and_reused_for_the_same_words(self, read_chapter):
        first = self.save("The market at dawn.")
        state = self.client.post(f"/learning-tools/book-scanner/readings/{first['id']}/audio/").json()
        self.assertEqual(state["audio"], "ready")
        self.assertEqual(read_chapter.call_count, 1)
        # Someone at another school scans the very same words: no new audio.
        other = self.user("other", "teacher", School.objects.create(name="Elsewhere", email="e@example.com"))
        self.client.force_login(other)
        second = self.save("The market at dawn.")
        state = self.client.post(f"/learning-tools/book-scanner/readings/{second['id']}/audio/").json()
        self.assertEqual(state["audio"], "ready")
        self.assertEqual(read_chapter.call_count, 1)
        a, b = ScanReading.objects.get(pk=first["id"]), ScanReading.objects.get(pk=second["id"])
        self.assertEqual(a.audio_file.name, b.audio_file.name)
        self.assertEqual(ReadAlongTiming.objects.get(object_id=b.pk).words, VOICE[1])
        # Deleting one keeps the recording the other still uses.
        scan_library.delete(b)
        self.assertTrue(a.audio_file.storage.exists(a.audio_file.name))

    def test_changing_someone_elses_reading_saves_your_own_copy(self):
        original = ScanReading.objects.create(owner=self.teacher, school=self.school, title="Page", text="Original words")
        self.client.force_login(self.student)
        saved = self.save("Original words, changed", id=original.pk)
        self.assertNotEqual(saved["id"], original.pk)
        original.refresh_from_db()
        self.assertEqual(original.text, "Original words")

    def test_only_the_maker_or_the_school_admin_can_delete(self):
        reading = ScanReading.objects.create(owner=self.teacher, school=self.school, title="Page", text="Words")
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(f"/learning-tools/book-scanner/readings/{reading.pk}/delete/").status_code, 403)
        admin = self.user("admin", "school_admin", self.school)
        self.client.force_login(admin)
        self.assertEqual(self.client.post(f"/learning-tools/book-scanner/readings/{reading.pk}/delete/").status_code, 200)
        self.assertFalse(ScanReading.objects.exists())

    @mock.patch("apps.diction_library.narration.read_chapter", return_value=VOICE)
    def test_the_audio_plays_in_the_protected_player_with_no_download(self, _read):
        saved = self.save("The market at dawn.")
        self.client.post(f"/learning-tools/book-scanner/readings/{saved['id']}/audio/")
        page = self.client.get(f"/learning-tools/book-scanner/?reading={saved['id']}")
        self.assertContains(page, "data-offline-keep")              # Save for offline
        self.assertContains(page, "/videos/play/")                   # through the protected player
        self.assertNotContains(page, ".mp3")                         # no address of the file itself
        self.assertNotContains(page, "Download audio")
        self.assertEqual(self.client.post("/learning-tools/book-scanner/narrate/").status_code, 404)
