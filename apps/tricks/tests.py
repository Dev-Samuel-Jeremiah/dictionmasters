from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.assessments.models import Assessment
from apps.book.models import Articulation, Sound, SoundCategory, WordBankEntry

from .models import LessonActivity, LessonActivityAttempt, LessonActivityItem

User = get_user_model()


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class TrickUnlockTests(TestCase):
    """Tricks are taken in order: finish a trick, pass its assessment, and
    only then does the next one open."""

    def setUp(self):
        group = SoundCategory.for_tricks()
        self.one = Sound.objects.create(category=group, name="-age Ending", symbol="-age", order=1)
        Articulation.objects.create(sound=self.one, trap_text="vil-LAGE", mouth_position_text="VIL-idge")
        WordBankEntry.objects.create(sound=self.one, word="village")
        self.two = Sound.objects.create(category=group, name="Weak forms", order=2)
        WordBankEntry.objects.create(sound=self.two, word="to")
        self.three = Sound.objects.create(category=group, name="Stress", order=3)

        self.test = LessonActivity.objects.create(lesson=self.one, kind="stress-placement",
                                                 title="Where is the stress?", pass_mark=70)
        self.question = LessonActivityItem.objects.create(activity=self.test, prompt="village",
                                                         options="vil\nlage", answer="vil")

        self.learner = User.objects.create_user(email="learner@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.learner)

    def take_test(self, answer, activity=None, question=None):
        activity, question = activity or self.test, question or self.question
        self.client.post(f"/tricks/lessons/{activity.lesson.slug}/assessment/{activity.slug}/",
                         {f"item-{question.pk}": answer})
        return LessonActivityAttempt.objects.filter(user=self.learner, activity=activity).latest("created_at")

    def open_every_tab(self, trick):
        for tab in ("lens", "word-bank"):
            self.client.get(f"/tricks/lessons/{trick.slug}/{tab}/")

    def test_only_the_first_trick_is_open_at_the_start(self):
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.one.slug}/").status_code, 200)
        locked = self.client.get(f"/tricks/lessons/{self.two.slug}/")
        self.assertEqual(locked.status_code, 403)
        self.assertContains(locked, "Trick 1: -age Ending", status_code=403)
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/word-bank/").status_code, 403)
        listing = self.client.get("/tricks/lessons/")
        self.assertContains(listing, "ui-numlist__item--current")
        self.assertContains(listing, "ui-numlist__item--locked", count=2)
        self.assertNotContains(listing, f'href="/tricks/lessons/{self.two.slug}/"')

    def test_the_assessment_waits_until_every_part_is_opened(self):
        page = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/")
        self.assertContains(page, "Not opened yet")
        self.assertContains(page, 'aria-disabled="true">Start')
        # Going round the gate is sent back to the trick.
        self.client.post(
            f"/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/", {f"item-{self.question.pk}": "vil"})
        self.assertFalse(LessonActivityAttempt.objects.filter(user=self.learner).exists())

        self.open_every_tab(self.one)
        page = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/")
        self.assertNotContains(page, "Not opened yet")
        self.assertContains(page, f'href="/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/"')
        activity = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/")
        self.assertContains(activity, "Word stress")
        self.assertContains(activity, 'name="item-')

    def test_failing_keeps_the_next_trick_locked_and_passing_opens_it(self):
        self.open_every_tab(self.one)
        failed = self.take_test("lage")
        self.assertFalse(failed.passed)
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 403)
        result = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/result/{failed.pk}/")
        self.assertContains(result, "1 activity left to pass")

        passed = self.take_test("vil")
        self.assertTrue(passed.passed)
        result = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/result/{passed.pk}/")
        self.assertContains(result, "Trick 2 is unlocked")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 200)
        # Only the one after it: Trick 3 waits for Trick 2.
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.assertContains(self.client.get("/tricks/lessons/"), "ui-numlist__item--done")

    def test_a_trick_without_an_assessment_opens_the_next_once_finished(self):
        self.open_every_tab(self.one)
        self.take_test("vil")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.client.get(f"/tricks/lessons/{self.two.slug}/word-bank/")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_an_empty_trick_still_has_to_be_opened(self):
        self.two.word_bank_entries.all().delete()
        self.open_every_tab(self.one)
        self.take_test("vil")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.client.get(f"/tricks/lessons/{self.two.slug}/")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_every_activity_must_be_passed_and_recordings_count_once_sent(self):
        sort = LessonActivity.objects.create(lesson=self.one, kind="sound-sort", title="Sort them",
                                            buckets="/ɪdʒ/\n/eɪdʒ/", order=2)
        village = LessonActivityItem.objects.create(activity=sort, prompt="village", answer="/ɪdʒ/")
        aloud = LessonActivity.objects.create(lesson=self.one, kind="read-aloud", title="Read it", order=3)
        line = LessonActivityItem.objects.create(activity=aloud, prompt="Our cottage is in the village.")
        self.open_every_tab(self.one)

        self.take_test("vil")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 403)
        self.assertTrue(self.take_test("/ɪdʒ/", sort, village).passed)
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 403)

        self.client.post(f"/tricks/lessons/{self.one.slug}/assessment/{aloud.slug}/",
                         {f"recording-{line.pk}": SimpleUploadedFile("me.webm", b"voice", content_type="audio/webm")})
        sent = LessonActivityAttempt.objects.get(user=self.learner, activity=aloud)
        self.assertEqual(sent.status, sent.STATUS_AWAITING)
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 200)

    def test_the_activity_pages_lead_back_to_the_trick(self):
        self.open_every_tab(self.one)
        page = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/{self.test.slug}/")
        self.assertContains(page, f'href="/tricks/lessons/{self.one.slug}/assessment/"')
        self.assertNotContains(page, 'href="/echospell/')
        self.assertNotContains(page, "Back to Group")

    def test_staff_see_every_trick(self):
        self.client.force_login(User.objects.create_user(
            email="staff@example.com", password="pw-12345678", first_name="Sam", is_staff=True))
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_the_control_room_sets_up_a_tricks_assessment(self):
        staff = User.objects.create_user(email="admin@example.com", password="pw-12345678", first_name="Sam",
                                         is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(f"/manage/trick-sounds/{self.one.pk}/"), "Where is the stress?")
        form = self.client.get(f"/manage/trick-activities/new/?in={self.two.pk}")
        self.assertContains(form, "Activity type")
        for label in ("Transcription", "Sound sort", "Minimal pairs", "Read aloud", "Sentence builder"):
            self.assertContains(form, label)
        self.client.post(f"/manage/trick-activities/new/?in={self.two.pk}", {
            "_in": self.two.pk, "kind": "minimal-pairs", "title": "Hear the difference", "pass_mark": 60,
            "order": 1, "is_published": "on",
        })
        self.assertEqual(LessonActivity.objects.get(title="Hear the difference").lesson, self.two)
        self.assertFalse(Assessment.objects.exists())

    def test_the_question_form_shows_only_what_the_activity_type_needs(self):
        self.client.force_login(User.objects.create_user(
            email="admin2@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))
        # Word stress is multiple choice: prompt, answer and options, no audio or picture.
        page = self.client.get(f"/manage/trick-activity-items/new/?in={self.test.pk}").content.decode()
        for name in ("prompt", "answer", "options", "hint"):
            self.assertIn(f'name="{name}"', page)
        for name in ("audio_file", "audio_url", "image"):
            self.assertNotIn(f'name="{name}"', page)
        self.assertIn("The stressed syllable", page)

        # Dictation: the audio is the question, so no prompt and no options.
        dictation = LessonActivity.objects.create(lesson=self.one, kind="dictation", title="Hear and spell")
        page = self.client.get(f"/manage/trick-activity-items/new/?in={dictation.pk}").content.decode()
        self.assertIn('name="audio_file"', page)
        self.assertNotIn('name="prompt"', page)
        self.assertNotIn('name="options"', page)

        # Read aloud: nothing to mark against, so no answer.
        aloud = LessonActivity.objects.create(lesson=self.one, kind="read-aloud", title="Say it")
        page = self.client.get(f"/manage/trick-activity-items/new/?in={aloud.pk}").content.decode()
        self.assertIn('name="prompt"', page)
        self.assertNotIn('name="answer"', page)

        # Saving still works with the fields left out.
        self.client.post(f"/manage/trick-activity-items/new/?in={aloud.pk}",
                         {"_in": aloud.pk, "order": 1, "prompt": "Our cottage is in the village."})
        self.assertTrue(aloud.items.filter(prompt__startswith="Our cottage").exists())

    def test_the_activity_form_follows_the_type_chosen(self):
        self.client.force_login(User.objects.create_user(
            email="admin3@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))
        page = self.client.get(f"/manage/trick-activities/new/?in={self.one.pk}")
        self.assertContains(page, 'id="kind-guide"')
        self.assertContains(page, "manage_kind_fields.js")
        guide = page.context["kind_guide"]
        self.assertEqual(guide["by_value"]["sound-sort"]["fields"], ["buckets"])
        self.assertEqual(guide["by_value"]["transcription"]["fields"], [])
        # Video and audio on the activity itself are never shown to learners.
        self.assertNotContains(page, 'name="video_file"')

    def test_a_sound_sort_question_picks_its_box(self):
        self.client.force_login(User.objects.create_user(
            email="admin4@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))
        sort = LessonActivity.objects.create(lesson=self.one, kind="sound-sort", title="Sort",
                                            buckets="/ɪdʒ/ as in village\n/eɪdʒ/ as in page")
        page = self.client.get(f"/manage/trick-activity-items/new/?in={sort.pk}")
        self.assertContains(page, '<option value="/ɪdʒ/ as in village">')
        self.client.post(f"/manage/trick-activity-items/new/?in={sort.pk}",
                         {"_in": sort.pk, "order": 1, "prompt": "cottage", "answer": "/ɪdʒ/ as in village"})
        self.assertEqual(sort.items.get(prompt="cottage").answer, "/ɪdʒ/ as in village")



@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AcademyUnlockTests(TestCase):
    """44 Academy works the same way: each sound has an assessment, and the
    sounds are taken in order."""

    def setUp(self):
        group = SoundCategory.objects.create(name="Long vowels", order=1)
        self.first = Sound.objects.create(category=group, symbol="iː", name="Long EE", order=1)
        WordBankEntry.objects.create(sound=self.first, word="sheep")
        self.second = Sound.objects.create(category=group, symbol="ɪ", name="Short I", order=2)
        WordBankEntry.objects.create(sound=self.second, word="ship")

        self.test = LessonActivity.objects.create(lesson=self.first, kind="minimal-pairs",
                                                  title="Sheep or ship?", pass_mark=70)
        self.question = LessonActivityItem.objects.create(activity=self.test, options="sheep\nship", answer="sheep")

        self.learner = User.objects.create_user(email="sam@example.com", password="pw-12345678", first_name="Sam")
        self.client.force_login(self.learner)

    def test_sounds_open_one_at_a_time(self):
        self.assertEqual(self.client.get(f"/book/44-academy/{self.first.slug}/").status_code, 200)
        locked = self.client.get(f"/book/44-academy/{self.second.slug}/")
        self.assertEqual(locked.status_code, 403)
        self.assertContains(locked, "Long EE", status_code=403)
        listing = self.client.get("/book/44-academy/")
        self.assertContains(listing, "ui-sound--locked")
        self.assertContains(listing, "Up next")
        self.assertNotContains(listing, f'href="/book/44-academy/{self.second.slug}/"')

    def test_a_sounds_assessment_unlocks_the_next_sound(self):
        page = self.client.get(f"/book/44-academy/{self.first.slug}/assessment/")
        self.assertContains(page, "Sheep or ship?")
        self.assertContains(page, "Minimal pairs")
        self.assertContains(page, 'aria-disabled="true">Start')

        self.client.get(f"/book/44-academy/{self.first.slug}/word-bank/")
        page = self.client.get(f"/book/44-academy/{self.first.slug}/assessment/")
        self.assertContains(page, f'href="/book/44-academy/{self.first.slug}/assessment/{self.test.slug}/"')

        self.client.post(f"/book/44-academy/{self.first.slug}/assessment/{self.test.slug}/",
                         {f"item-{self.question.pk}": "ship"})
        self.assertEqual(self.client.get(f"/book/44-academy/{self.second.slug}/").status_code, 403)

        self.client.post(f"/book/44-academy/{self.first.slug}/assessment/{self.test.slug}/",
                         {f"item-{self.question.pk}": "sheep"})
        attempt = LessonActivityAttempt.objects.filter(activity=self.test).latest("created_at")
        self.assertTrue(attempt.passed)
        result = self.client.get(
            f"/book/44-academy/{self.first.slug}/assessment/{self.test.slug}/result/{attempt.pk}/")
        self.assertContains(result, "Sound 2 is unlocked")
        self.assertNotContains(result, "Trick 2")
        self.assertEqual(self.client.get(f"/book/44-academy/{self.second.slug}/").status_code, 200)
        self.assertContains(self.client.get("/accounts/dashboard/"), "1 of 2 complete")

    def test_the_two_programmes_are_counted_apart(self):
        from apps.book.models import TRICKS

        trick = Sound.objects.create(category=SoundCategory.for_tricks(), name="Linking", order=1)
        WordBankEntry.objects.create(sound=trick, word="an apple")
        # Finishing a sound doesn't touch the tricks, and the other way round.
        self.client.get(f"/book/44-academy/{self.first.slug}/word-bank/")
        from apps.tricks.progress import Standing

        self.assertEqual(Standing(self.learner, TRICKS).done, 0)
        self.assertEqual(Standing(self.learner, TRICKS).steps[0]["lesson"], trick)
        self.assertEqual(self.client.get(f"/tricks/lessons/{trick.slug}/").status_code, 200)

    def test_the_control_room_has_a_sounds_assessment(self):
        self.client.force_login(User.objects.create_user(
            email="admin5@example.com", password="pw-12345678", first_name="Sam", is_staff=True, is_superuser=True))
        self.assertContains(self.client.get(f"/manage/sounds/{self.first.pk}/"), "Sheep or ship?")
        listing = self.client.get("/manage/sound-activities/")
        self.assertContains(listing, "Sheep or ship?")
        # Each programme's screens show only its own.
        LessonActivity.objects.create(lesson=Sound.objects.create(category=SoundCategory.for_tricks(), name="A trick"),
                                      kind="transcription", title="A trick's check")
        self.assertNotContains(self.client.get("/manage/sound-activities/"), "A trick's check")
        self.assertNotContains(self.client.get("/manage/trick-activities/"), "Sheep or ship?")
        form = self.client.get(f"/manage/sound-activities/new/?in={self.second.pk}")
        self.assertContains(form, "Activity type")
        self.client.post(f"/manage/sound-activities/new/?in={self.second.pk}",
                         {"_in": self.second.pk, "kind": "odd-one-out", "title": "Odd one out", "pass_mark": 70,
                          "order": 1, "is_published": "on"})
        self.assertEqual(LessonActivity.objects.get(title="Odd one out").lesson, self.second)
