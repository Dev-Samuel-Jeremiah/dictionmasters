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


# ----------------------------------------------------------- unlocking offline

FIXED_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


@override_settings(DESKTOP_CONTENT_KEY=FIXED_KEY)
class UnlockCodeTests(TestCase):
    """unlock.py. The same example is in the app's tests (test/unlock.test.js):
    the two must always agree."""

    def test_the_example_the_app_checks_too(self):
        import datetime

        from . import unlock

        computer = unlock.computer_number("0f3c2a6e9b7d4e1f8a2b3c4d5e6f7a8b")
        self.assertEqual(computer, "7GF38R79")
        self.assertEqual(unlock.make_code(computer, "Level 1", datetime.date(2027, 7, 31)), "DM-GXXA-NBMH-8NAY-V6EM-GN7H")
        self.assertEqual(unlock.factor("Level 1").hex(), "59807329d4957ccb")

    def test_a_code_opens_one_level_on_one_computer(self):
        import datetime

        from . import unlock

        here, there = unlock.computer_number("machine-a"), unlock.computer_number("machine-b")
        code = unlock.make_code(here, "Level 3", datetime.date(2027, 1, 31))
        self.assertEqual(unlock.read_code(code.lower().replace("-", " "), unlock.show_computer(here)),
                         {"level": "Level 3", "until": datetime.date(2027, 1, 31)})
        self.assertIsNone(unlock.read_code(code, there), "another computer")
        typo = code[:-1] + ("A" if code[-1] != "A" else "B")
        self.assertIsNone(unlock.read_code(typo, here), "a typing mistake")
        self.assertEqual(unlock.read_code(unlock.make_code(here, "Pre-Level"), here)["until"], None)

    def test_the_end_date_cant_be_edited(self):
        """Changing the date bits inside a code changes the mask, so the
        factor comes out wrong (and the check catches it first)."""
        import datetime

        from . import unlock

        here = unlock.computer_number("machine-a")
        code = unlock.make_code(here, "Level 1", datetime.date(2026, 12, 31))
        value = unlock._number(unlock._letters(code)[2:]) >> 12
        later = value + (365 << 64)                       # a year more
        forged = unlock._chars(later << 12 | unlock._check(later), unlock.CODE_CHARS)
        self.assertIsNone(unlock.read_code(forged, here))

    def test_computer_numbers_catch_mistakes(self):
        from . import unlock

        number = unlock.computer_number("machine-a")
        self.assertEqual(unlock.clean_computer(unlock.show_computer(number).lower()), number)
        wrong = number[:2] + ("A" if number[2] != "A" else "B") + number[3:]
        self.assertEqual(unlock.clean_computer(wrong), "")
        self.assertEqual(unlock.clean_computer("K7QX"), "")

    def test_the_keys_open_only_with_the_right_factor(self):
        from . import keys, unlock

        wrapped = unlock.wrap("Level 2")
        opened = unlock.unwrap(wrapped, "Level 2", unlock.factor("Level 2"))
        self.assertEqual(opened, {"Level 2": keys.content_key_b64("Level 2"), "common": keys.content_key_b64("common")})
        self.assertIsNone(unlock.unwrap(wrapped, "Level 2", unlock.factor("Level 3")))
        self.assertIsNone(unlock.unwrap(wrapped, "Level 3", unlock.factor("Level 2")), "a wrap for one level only")


@override_settings(DESKTOP_CONTENT_KEY=FIXED_KEY)
class UnlockAdminAndCheckTests(TestCase):
    def setUp(self):
        from apps.accounts.models import User

        from . import unlock

        self.admin = User.objects.create_superuser("boss@example.com", "pw-12345678", first_name="Boss")
        self.client.force_login(self.admin)
        self.computer = unlock.computer_number("school-pc-1")

    def unlock_it(self, **extra):
        from .models import ComputerUnlock

        fields = {"computer": self.computer[:4].lower() + "-" + self.computer[4:], "level": "Level 1",
                  "valid_until": "", "holder": "White Diamonds Academy", "notes": ""}
        fields.update(extra)
        response = self.client.post("/admin/desktop_edition/computerunlock/add/", fields, follow=True)
        return response, ComputerUnlock.objects.order_by("-pk").first()

    def test_unlocking_a_computer_in_the_control_room(self):
        from . import unlock

        response, record = self.unlock_it(valid_until="2027-07-31")
        self.assertEqual(record.computer, self.computer)
        self.assertContains(response, record.code)
        self.assertEqual(unlock.read_code(record.code, self.computer)["level"], "Level 1")
        self.assertEqual(record.created_by, self.admin)
        response, _ = self.unlock_it(computer="K7QX-3MPA")
        self.assertContains(response, "check each character")

    def test_an_unlocked_computer_going_online_gets_new_lessons(self):
        import json

        _response, record = self.unlock_it()
        check = self.client.post("/desktop-app/check/", json.dumps({"computer": self.computer, "unlock": record.code}),
                                 content_type="application/json").json()
        self.assertTrue(check["ok"])
        self.assertEqual(set(check["keys"]), {"common", "Level 1"})
        latest = self.client.get("/desktop-app/content/latest/", HTTP_X_DM_LICENCE=f"{check['licence']}.{check['signature']}")
        self.assertEqual(latest.status_code, 200)
        again = self.client.post("/desktop-app/check/", json.dumps({"licence": check["licence"], "signature": check["signature"]}),
                                 content_type="application/json").json()
        self.assertTrue(again["ok"])
        record.revoked = True
        record.save()
        stopped = self.client.post("/desktop-app/check/", json.dumps({"computer": self.computer, "unlock": record.code}),
                                   content_type="application/json").json()
        self.assertTrue(stopped["stopped"])
        self.assertEqual(self.client.get("/desktop-app/content/latest/",
                                         HTTP_X_DM_LICENCE=f"{check['licence']}.{check['signature']}").status_code, 403)

    def test_a_right_code_with_no_record_isnt_stopped(self):
        import json

        from . import unlock

        code = unlock.make_code(self.computer, "Level 2")
        answer = self.client.post("/desktop-app/check/", json.dumps({"computer": self.computer, "unlock": code}),
                                  content_type="application/json")
        self.assertEqual(answer.status_code, 404)
        self.assertNotIn("stopped", answer.json())
