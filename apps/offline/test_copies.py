"""Pages kept for offline use aren't visits (apps/offline/copies.py)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.book.models import Articulation, Sound, SoundCategory, WordBankEntry
from apps.echospell.models import CardPosition, GroupProgress, GroupStepsSeen
from apps.learning_modules.models import Day, DayItemsSeen, DayProgress, LearningModule, LessonItem, Term, Week
from apps.tricks.models import LessonActivity, LessonActivityAttempt, LessonActivityItem, LessonProgress

from .tests import ManifestCase

User = get_user_model()
COPY = {"HTTP_X_DM_OFFLINE_COPY": "1"}
REPLAY = {"HTTP_X_DM_OFFLINE_REPLAY": "1"}


class EchoSpellCopyTests(ManifestCase):
    def test_keeping_a_card_page_records_nothing(self):
        self.client.force_login(self.pupil)
        url = reverse("echospell:card_detail", args=[self.one.slug, self.group.slug, self.words.slug])
        self.assertEqual(self.client.get(url, **COPY).status_code, 200)
        self.client.get(reverse("echospell:group_detail", args=[self.one.slug, self.group.slug]), **COPY)
        self.assertFalse(CardPosition.objects.filter(user=self.pupil).exists(), "pick up where you left off is theirs")
        self.assertFalse(GroupStepsSeen.objects.filter(user=self.pupil).exists())
        self.assertFalse(GroupProgress.objects.filter(user=self.pupil).exists())
        # Opening it (online, or replayed from offline) counts as before.
        self.client.get(url, **REPLAY)
        self.assertTrue(CardPosition.objects.filter(user=self.pupil, group=self.group).exists())
        self.assertTrue(GroupStepsSeen.objects.filter(user=self.pupil, group=self.group).exists())


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class TricksCopyTests(TestCase):
    def setUp(self):
        group = SoundCategory.for_tricks()
        self.trick = Sound.objects.create(category=group, name="-age Ending", symbol="-age", order=1)
        Articulation.objects.create(sound=self.trick, trap_text="vil-LAGE", mouth_position_text="VIL-idge")
        WordBankEntry.objects.create(sound=self.trick, word="village")
        self.test = LessonActivity.objects.create(lesson=self.trick, kind="stress-placement",
                                                 title="Where is the stress?", pass_mark=70)
        self.question = LessonActivityItem.objects.create(activity=self.test, prompt="village",
                                                         options="vil\nlage", answer="vil")
        self.learner = User.objects.create_user(email="copy@example.com", password="pw-12345678", first_name="Ada")
        self.client.force_login(self.learner)
        self.activity = f"/tricks/lessons/{self.trick.slug}/assessment/{self.test.slug}/"

    def test_keeping_a_tab_records_nothing(self):
        self.client.get(f"/tricks/lessons/{self.trick.slug}/word-bank/", **COPY)
        self.assertFalse(LessonProgress.objects.filter(user=self.learner).exists())
        self.client.get(f"/tricks/lessons/{self.trick.slug}/word-bank/")
        self.assertEqual(LessonProgress.objects.get(user=self.learner).tabs_seen, ["word-bank"])

    def test_an_activity_is_kept_ready_before_every_part_is_opened(self):
        self.assertEqual(self.client.get(self.activity).status_code, 302)        # online: open every part first
        kept = self.client.get(self.activity, **COPY)
        self.assertContains(kept, 'name="item-')

    def test_answers_given_offline_are_marked(self):
        answers = {f"item-{self.question.pk}": "vil"}
        self.client.post(self.activity, answers)
        self.assertFalse(LessonActivityAttempt.objects.exists(), "online, the rule stands")
        self.client.post(self.activity, answers, **REPLAY)
        self.assertTrue(LessonActivityAttempt.objects.get(user=self.learner).passed)

    def test_a_kept_trick_opens_just_as_it_does_online(self):
        """A copy never opens anything a learner can't: locked stays locked."""
        later = Sound.objects.create(category=self.trick.category, name="Weak forms", order=2)
        WordBankEntry.objects.create(sound=later, word="to")
        online = self.client.get(f"/tricks/lessons/{later.slug}/word-bank/").status_code
        self.assertEqual(self.client.get(f"/tricks/lessons/{later.slug}/word-bank/", **COPY).status_code, online)


class LearningModulesCopyTests(TestCase):
    def setUp(self):
        LearningModule.objects.all().delete()
        module = LearningModule.objects.create(name="Sound Discovery", slug="sound-discovery")
        week = Week.objects.create(term=Term.objects.create(module=module, name="First Term"), number=1)
        self.day = Day.objects.create(week=week, day_name="monday")
        Day.objects.create(week=week, day_name="tuesday")
        for n, title in enumerate(["Meet the sound", "Say it"]):
            LessonItem.objects.create(day=self.day, title=title, order=n)
        self.pupil = User.objects.create_user("lm@example.com", "pw-12345678", first_name="Bo", role="student", level="Level 1")
        self.client.force_login(self.pupil)
        self.url = "/learning-modules/sound-discovery/first-term/week-1/monday/"

    def test_keeping_each_step_records_nothing(self):
        for step in ("", "?step=1", "?step=2", "?step=finish"):
            self.assertEqual(self.client.get(self.url + step, **COPY).status_code, 200)
        self.assertFalse(DayItemsSeen.objects.filter(user=self.pupil).exists())
        self.assertFalse(DayProgress.objects.filter(user=self.pupil).exists())
        self.assertContains(self.client.get(self.url + "?step=2", **COPY), "Step 2 of 2")
        # The same steps opened offline and replayed earn the day.
        for step in ("?step=1", "?step=2"):
            self.client.get(self.url + step, **REPLAY)
        self.assertTrue(DayProgress.objects.filter(user=self.pupil, day=self.day).exists())
