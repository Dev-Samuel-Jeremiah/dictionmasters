from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.assessments.models import Assessment, Attempt, Question
from apps.book.models import Articulation, SoundCategory, Sound, WordBankEntry

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

        self.test = Assessment.objects.create(title="-age Ending check", trick=self.one, pass_mark=70,
                                              kind=Assessment.Kind.PRACTICE, shuffle_questions=False)
        self.question = Question.objects.create(
            assessment=self.test, type=Question.Type.CHOICE, prompt="How is village said?",
            options="VIL-idge\nvil-LAGE", answer="VIL-idge")

        self.learner = User.objects.create_user(email="learner@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.learner)

    def take_test(self, answer):
        self.client.post(f"/assessments/{self.test.slug}/start/")
        attempt = Attempt.objects.filter(user=self.learner, assessment=self.test).latest("started_at")
        self.client.post(f"/assessments/attempt/{attempt.pk}/", {f"q-{self.question.pk}": answer})
        attempt.refresh_from_db()
        return attempt

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
        self.assertContains(page, "disabled>Start the assessment")
        # Going round the gate is sent back to the trick.
        self.client.post(f"/assessments/{self.test.slug}/start/")
        self.assertFalse(Attempt.objects.filter(user=self.learner).exists())

        self.open_every_tab(self.one)
        page = self.client.get(f"/tricks/lessons/{self.one.slug}/assessment/")
        self.assertNotContains(page, "Not opened yet")
        self.assertContains(page, f'action="/assessments/{self.test.slug}/start/"')

    def test_failing_keeps_the_next_trick_locked_and_passing_opens_it(self):
        self.open_every_tab(self.one)
        failed = self.take_test("vil-LAGE")
        self.assertFalse(failed.passed)
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 403)
        result = self.client.get(f"/assessments/attempt/{failed.pk}/result/")
        self.assertContains(result, "You need 70%")

        passed = self.take_test("VIL-idge")
        self.assertTrue(passed.passed)
        result = self.client.get(f"/assessments/attempt/{passed.pk}/result/")
        self.assertContains(result, "Trick 2 is unlocked")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.two.slug}/").status_code, 200)
        # Only the one after it: Trick 3 waits for Trick 2.
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.assertContains(self.client.get("/tricks/lessons/"), "ui-numlist__item--done")

    def test_a_trick_without_an_assessment_opens_the_next_once_finished(self):
        self.open_every_tab(self.one)
        self.take_test("VIL-idge")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.client.get(f"/tricks/lessons/{self.two.slug}/word-bank/")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_an_empty_trick_still_has_to_be_opened(self):
        self.two.word_bank_entries.all().delete()
        self.open_every_tab(self.one)
        self.take_test("VIL-idge")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 403)
        self.client.get(f"/tricks/lessons/{self.two.slug}/")
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_trick_assessments_stay_out_of_the_general_assessment_lists(self):
        self.assertNotContains(self.client.get("/assessments/type/practice/"), "-age Ending check")

    def test_staff_see_every_trick(self):
        self.client.force_login(User.objects.create_user(
            email="staff@example.com", password="pw-12345678", first_name="Sam", is_staff=True))
        self.assertEqual(self.client.get(f"/tricks/lessons/{self.three.slug}/").status_code, 200)

    def test_the_control_room_sets_up_a_tricks_assessment(self):
        staff = User.objects.create_user(email="admin@example.com", password="pw-12345678", first_name="Sam",
                                         is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(f"/manage/trick-sounds/{self.one.pk}/"), "-age Ending check")
        self.assertContains(self.client.get("/manage/trick-assessments/"), "-age Ending check")
        self.assertNotContains(self.client.get("/manage/assessments/"), "-age Ending check")
        self.client.post(f"/manage/trick-assessments/new/?in={self.two.pk}", {
            "_in": self.two.pk, "title": "Weak forms check", "kind": "practice", "pass_mark": 60,
            "max_attempts": 0, "shuffle_questions": "on", "is_published": "on",
        })
        self.assertEqual(Assessment.objects.get(title="Weak forms check").trick, self.two)
