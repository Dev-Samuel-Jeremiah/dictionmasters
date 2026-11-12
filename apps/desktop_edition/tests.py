import json
import shutil
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import keys
from .export import Media, blob_path, build, read_manifest, write_folder
from .models import Activation, ActivationCode, ContentRelease, clean_code


class CodeTests(TestCase):
    def test_codes_are_typed_forgivingly(self):
        self.assertEqual(clean_code("dm-abcd-efgh-jkmn"), "DM-ABCD-EFGH-JKMN")
        self.assertEqual(clean_code(" abcd efgh jkmn "), "DM-ABCD-EFGH-JKMN")
        self.assertEqual(clean_code("DM-ABC"), "")

    def test_every_level_when_none_ticked(self):
        code = ActivationCode.objects.create(holder="A school")
        self.assertIn("Level 12", code.opens())
        code.set_levels(["Level 1", "Level 2"])
        self.assertEqual(code.opens(), ["Level 1", "Level 2"])

    def test_make_activation_codes(self):
        call_command("make_activation_codes", holder="White Diamonds", count=3, levels="Level 1", seats=2,
                     until="2030-01-01", stdout=open("/dev/null", "w"))
        self.assertEqual(ActivationCode.objects.filter(holder="White Diamonds", seats=2, levels=",Level 1,").count(), 3)


class LicenceTests(TestCase):
    def test_signed_licence_round_trip(self):
        body, signature = keys.sign({"a": 1, "levels": ["Level 1"]})
        self.assertEqual(keys.verify(body, signature)["levels"], ["Level 1"])
        edited = keys.sign({"a": 1, "levels": ["Level 1", "Level 6"]})[0]
        self.assertIsNone(keys.verify(edited, signature))

    def test_sealing_round_trip_and_levels_differ(self):
        data = b"x" * (keys.PIECE * 2 + 17)
        sealed = keys.seal(data, "Level 1")
        self.assertEqual(keys.unseal(sealed, "Level 1"), data)
        with self.assertRaises(Exception):
            keys.unseal(sealed, "Level 2")
        self.assertEqual(keys.unseal(keys.seal(b"", "common"), "common"), b"")


def post(client, name, data):
    return client.post(reverse(f"desktop_edition:{name}"), json.dumps(data), content_type="application/json")


class ActivateTests(TestCase):
    def setUp(self):
        self.code = ActivationCode.objects.create(holder="Smart Gems", seats=1)
        self.code.set_levels(["Level 1"])
        self.code.save()

    def activate(self, device="pc-1", code=None):
        return post(self.client, "activate", {"code": code or self.code.code.lower(), "device_id": device,
                                              "device_name": "Lab PC", "learner_name": "Ada", "system": "windows"})

    def test_activate_gives_a_signed_licence_and_its_levels_keys(self):
        response = self.activate()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        licence = keys.verify(data["licence"], data["signature"])
        self.assertEqual(licence["levels"], ["Level 1"])
        self.assertEqual(licence["learner"], "Ada")
        self.assertEqual(set(data["keys"]), {"common", "Level 1"})
        self.assertEqual(Activation.objects.get().device_name, "Lab PC")

    def test_seats_are_counted_but_the_same_computer_can_activate_again(self):
        self.assertEqual(self.activate("pc-1").status_code, 200)
        self.assertEqual(self.activate("pc-1").status_code, 200)
        response = self.activate("pc-2")
        self.assertEqual(response.status_code, 403)
        self.assertIn("1 computer", response.json()["error"])
        Activation.objects.filter(device_id="pc-1").update(revoked=True)
        self.assertEqual(self.activate("pc-2").status_code, 200)

    def test_unknown_stopped_and_ended_codes(self):
        self.assertEqual(self.activate(code="DM-AAAA-BBBB-CCCC").status_code, 404)
        self.assertEqual(self.activate(code="nonsense").status_code, 400)
        ActivationCode.objects.filter(pk=self.code.pk).update(valid_until=date.today() - timedelta(days=1))
        self.assertIn("ended", self.activate().json()["error"])
        ActivationCode.objects.filter(pk=self.code.pk).update(is_active=False, valid_until=None)
        self.assertIn("stopped", self.activate().json()["error"])

    def test_check_in_and_a_freed_seat(self):
        data = self.activate().json()
        response = post(self.client, "check", {"licence": data["licence"], "signature": data["signature"], "release": 4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Activation.objects.get().content_release, 4)
        Activation.objects.update(revoked=True)
        response = post(self.client, "check", {"licence": data["licence"], "signature": data["signature"]})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["stopped"])

    def test_content_needs_a_licence_and_shows_only_its_levels(self):
        self.assertEqual(self.client.get(reverse("desktop_edition:latest")).status_code, 403)
        manifest = {"format": 1, "release": 1, "common": {"files": {}},
                    "levels": {"Level 1": {"files": {}}, "Level 6": {"files": {}}}}
        from django.core.files.storage import default_storage

        name = default_storage.save("desktop-content/releases/test.json", ContentFile(json.dumps(manifest).encode()))
        ContentRelease.objects.create(status=ContentRelease.Status.READY, manifest=name)
        data = self.activate().json()
        header = {"HTTP_X_DM_LICENCE": f"{data['licence']}.{data['signature']}"}
        response = self.client.get(reverse("desktop_edition:latest"), **header)
        self.assertEqual(list(response.json()["levels"]), ["Level 1"])
        with override_settings(DESKTOP_BUILD_TOKEN="secret-build"):
            response = self.client.get(reverse("desktop_edition:latest"), HTTP_X_DM_BUILD_TOKEN="secret-build")
            self.assertEqual(set(response.json()["levels"]), {"Level 1", "Level 6"})
        default_storage.delete(name)


class ExportTests(TestCase):
    """A release of the sample Level 1 lessons, end to end."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_level_one", stdout=open("/dev/null", "w"))

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(shutil.rmtree, self.out, True)
        override = override_settings(MEDIA_ROOT=self.media, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        })
        override.enable()
        self.addCleanup(override.disable)

    def test_release_holds_pages_answers_and_recordings_sealed(self):
        from apps.echospell.models import CardLesson

        card = CardLesson.objects.filter(group__level__name="Level 1").first()
        audio_field = next(f.name for f in CardLesson._meta.concrete_fields
                           if f.get_internal_type() == "FileField" and "audio" in f.name)
        getattr(card, audio_field).save("cat.mp3", ContentFile(b"ID3 fake recording"), save=True)

        with patch("apps.desktop_edition.export._fonts", side_effect=OSError("offline")):
            release = build(ContentRelease.objects.create(levels="Level 1"))
        self.assertEqual(release.status, ContentRelease.Status.READY)
        manifest = read_manifest(release)
        level = manifest["levels"]["Level 1"]
        self.assertIn(level["home"], level["files"])
        self.assertTrue(any(path.startswith("/static/css/") for path in manifest["common"]["files"]))

        stored = [path for path in level["files"] if path.startswith("/_m/")]
        self.assertTrue(stored, "the card's recording is kept")
        entry = level["files"][stored[0]]
        from django.core.files.storage import default_storage

        with default_storage.open(blob_path(entry["b"]), "rb") as handle:
            self.assertEqual(keys.unseal(handle.read(), "Level 1"), b"ID3 fake recording")

        answers_entry = level["files"]["/_dm/answers.json"]
        with default_storage.open(blob_path(answers_entry["b"]), "rb") as handle:
            answers = json.loads(keys.unseal(handle.read(), "Level 1"))
        missing = next(data for data in answers.values() if data["kind"] == "missing-letters")
        self.assertEqual(missing["items"][0]["answers"], ["cat"])

        pages_with_recording = 0
        for path, entry in level["files"].items():
            if entry["t"].startswith("text/html"):
                with default_storage.open(blob_path(entry["b"]), "rb") as handle:
                    html = keys.unseal(handle.read(), "Level 1").decode()
                self.assertNotIn("/media/", html)
                pages_with_recording += stored[0] in html
        self.assertTrue(pages_with_recording)
        self.assertTrue(any(path.startswith("/_ra/") for path in level["files"]), "read-along timings kept")

        # A second release uploads nothing new.
        with patch("apps.desktop_edition.export._fonts", side_effect=OSError("offline")):
            again = build(ContentRelease.objects.create(levels="Level 1"))
        self.assertEqual(again.new_size, 0)
        self.assertEqual(write_folder(read_manifest(again), self.out), len({
            e["b"] for group in [manifest["common"], level] for e in group["files"].values()}))

    def test_addresses_are_rewritten(self):
        media = Media(fetch_linked=True)
        html = ('<img src="https://www.dictionmasters.app/static/img/a.png"> <a href="https://youtube.com/watch?v=1">v</a> '
                '<audio src="https://cdn.example.com/sounds/cat.mp3?x=1&amp;y=2"></audio>')
        out = media.rewrite(html)
        self.assertIn('src="/static/img/a.png"', out)
        self.assertIn("https://youtube.com/watch?v=1", out)
        self.assertRegex(out, r'src="/_x/[0-9a-f]{24}\.mp3"')
        self.assertEqual(list(media.wanted.values())[0], ("web", "https://cdn.example.com/sounds/cat.mp3?x=1&y=2"))


class HiddenPupilTests(TestCase):
    """The pupils lessons are rendered as aren't learners or customers: no
    weekly email (their .invalid inbox would bounce it), not in the control
    room's figures."""

    def test_left_out_of_emails_and_figures(self):
        from django.utils import timezone

        from apps.accounts.models import User
        from apps.accounts.weekly import _due
        from apps.manage import analytics

        from .export import export_user

        pupil = User.objects.create_user("real@example.com", "pw-12345678", first_name="Ada", role="student", level="Level 1")
        hidden = export_user("Level 1")
        due = set(_due(User.objects.filter(role=User.Role.STUDENT), timezone.now()))
        self.assertIn(pupil, due)
        self.assertNotIn(hidden, due)
        totals = analytics.build({})["totals"]
        self.assertEqual(totals["students"], 1)
        self.assertEqual(totals["paying"], 0, "its endless plan isn't a paying customer")
