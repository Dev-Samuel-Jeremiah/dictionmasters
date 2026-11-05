"""Lesson packs: building one, what's in it, and who may open it."""

import base64
import os
import shutil
import tempfile
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from apps.assembly_recitals.models import Recital, Section

from .models import LessonPack
from .packs import build, new_key, read_index

User = get_user_model()
MEDIA = tempfile.mkdtemp()
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def opened(raw, key, parts):
    cipher = AESGCM(base64.b64decode(key))
    return b"".join(cipher.decrypt(base64.b64decode(iv), raw[offset:offset + length], None) for offset, length, iv in parts)


@override_settings(STORAGES=STORAGES, MEDIA_ROOT=MEDIA, MEDIA_URL="/media/")
class PackTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.addCleanup(cache.clear)
        cache.clear()
        section = Section.objects.create(name="Verses", slug="verses")
        self.audio = os.urandom(5 * 1024 * 1024 + 123)                  # more than one 4 MB piece
        self.video = os.urandom(300 * 1024)
        self.recital = Recital.objects.create(section=section, title="Psalm", slug="psalm", video_caption="Psalm video")
        self.recital.audio_file.save("psalm.mp3", ContentFile(self.audio), save=False)
        self.recital.video_file.save("psalm.mp4", ContentFile(self.video), save=False)
        self.recital.save()
        self.pack = LessonPack.objects.create(level="Level 1", key=new_key())

    def test_every_file_comes_back_exactly_with_the_key(self):
        build(self.pack)
        self.pack.refresh_from_db()
        self.assertEqual(self.pack.status, LessonPack.Status.READY)
        raw = self.pack.file.read()
        index = read_index(raw)
        stored = "/media/" + self.recital.audio_file.name                 # where the app keeps it
        audio = next(f for f in index["files"] if f["k"] == stored)
        self.assertEqual(len(audio["parts"]), 2)
        self.assertEqual(opened(raw, self.pack.key, audio["parts"]), self.audio)
        self.assertEqual(audio["size"], len(self.audio))
        video = index["videos"][0]
        self.assertEqual(video["title"], "Psalm video")
        self.assertEqual(opened(raw, self.pack.key, video["parts"]), self.video)
        self.assertEqual((self.pack.videos, self.pack.missing), (1, 0))
        self.assertNotIn(self.audio[:64], raw, "nothing readable without the key")
        with self.assertRaises(Exception):
            opened(raw, new_key(), audio["parts"])                         # another key gets nothing

    def test_a_missing_file_is_counted_and_left_out(self):
        os.remove(self.recital.audio_file.path)
        build(self.pack)
        self.pack.refresh_from_db()
        self.assertEqual((self.pack.status, self.pack.missing), (LessonPack.Status.READY, 1))

    def test_a_new_pack_replaces_the_old_one(self):
        build(self.pack)
        old_file = self.pack.file.path
        newer = build(LessonPack.objects.create(level="Level 1", key=new_key()))
        self.assertFalse(LessonPack.objects.filter(pk=self.pack.pk).exists())
        self.assertFalse(os.path.exists(old_file))
        self.assertTrue(os.path.exists(newer.file.path))


@override_settings(STORAGES=STORAGES, MEDIA_ROOT=MEDIA, MEDIA_URL="/media/")
class WhoGetsTheKeyTests(TestCase):
    def setUp(self):
        self.pack = LessonPack.objects.create(level="Level 1", key=new_key(), status=LessonPack.Status.READY)
        self.url = f"/offline-sync/pack/{self.pack.pk}/"

    def ask(self, **extra):
        self.client.force_login(User.objects.create_user(f"{len(extra)}{os.urandom(3).hex()}@example.com", "pw-12345678",
                                                         first_name="Ada", **extra))
        return self.client.get(self.url)

    def test_a_learner_of_that_level(self):
        answer = self.ask(role="student", level="Level 1")
        self.assertEqual(answer.json()["key"], self.pack.key)
        self.assertIn("no-store", answer["Cache-Control"])

    def test_not_another_level_or_signed_out(self):
        self.assertEqual(self.ask(role="student", level="Level 2").status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_not_once_their_plan_has_ended(self):
        with patch("apps.offline.views.has_access", return_value=False):
            self.assertEqual(self.ask(role="student", level="Level 1").status_code, 403)

    def test_not_a_pack_still_being_built(self):
        LessonPack.objects.filter(pk=self.pack.pk).update(status=LessonPack.Status.BUILDING)
        self.assertEqual(self.ask(role="student", level="Level 1").status_code, 404)


class ControlRoomTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("staff@example.com", "pw-12345678", first_name="Sam", is_staff=True))

    def test_building_starts_in_its_own_process(self):
        with patch("apps.manage.lesson_packs.subprocess.Popen") as started:
            response = self.client.post("/manage/lesson-packs/build/", {"level": "Level 3"})
            self.assertRedirects(response, "/manage/lesson-packs/")
            pack = LessonPack.objects.get()
            self.assertEqual(started.call_args.args[0][-2:], ["build_lesson_pack", str(pack.pk)])
            self.assertTrue(started.call_args.kwargs["start_new_session"])
            self.client.post("/manage/lesson-packs/build/", {"level": "Level 3"})
            self.assertEqual(LessonPack.objects.count(), 1, "not twice at once")
        page = self.client.get("/manage/lesson-packs/")
        self.assertContains(page, "Waiting to start")
        self.assertContains(page, 'http-equiv="refresh"')

    def test_only_staff(self):
        self.client.force_login(User.objects.create_user("t@example.com", "pw-12345678", first_name="T", role="teacher"))
        self.assertEqual(self.client.get("/manage/lesson-packs/").status_code, 302)
