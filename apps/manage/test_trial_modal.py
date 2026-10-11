"""The trial modal on Schools & people (views.extend_trial): add free trial
to a school or a learner whose access has ended, or is about to."""

from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Subscription
from apps.schools.models import School

User = get_user_model()


def person(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class TrialModalTests(TestCase):
    url = "/manage/trial/extend/"

    def setUp(self):
        self.staff = person("staff@example.com", is_staff=True)
        self.client.force_login(self.staff)
        self.ended = School.objects.create(name="Ended School", email="e@example.com")
        Subscription.objects.create(school=self.ended, trial_ends_at=timezone.now() - timedelta(days=3))
        self.running = School.objects.create(name="Running School", email="r@example.com")
        self.ends = timezone.now() + timedelta(days=5)
        Subscription.objects.create(school=self.running, trial_ends_at=self.ends)

    def test_an_ended_schools_card_opens_the_modal(self):
        page = self.client.get("/manage/schools-directory/").content.decode()
        card = page[page.index("Ended School") - 1500:page.index("Ended School")]
        self.assertIn("data-trial-expired", card)
        self.assertIn(f'data-trial-target="school:{self.ended.pk}"', page)
        self.assertIn("Their free trial ended on", page)
        self.assertIn("data-trial-modal", page)
        running = page[page.index("Running School") - 1500:page.index("Running School")]
        self.assertNotIn("data-trial-expired", running)                 # opens the school as usual

    def test_adding_trial_to_an_ended_school_counts_from_today(self):
        response = self.client.post(self.url, {"target": f"school:{self.ended.pk}", "length": "14", "unit": "days",
                                               "next": "/manage/schools-directory/"}, follow=True)
        self.assertRedirects(response, "/manage/schools-directory/")
        self.assertContains(response, "Ended School: 14 days more free trial")
        ends = Subscription.objects.get(school=self.ended).trial_ends_at
        self.assertAlmostEqual(ends.timestamp(), (timezone.now() + timedelta(days=14)).timestamp(), delta=60)
        self.assertTrue(LogEntry.objects.filter(change_message__startswith="Free trial extended by 14 days").exists())

    def test_a_running_trial_is_added_to_its_end(self):
        self.client.post(self.url, {"target": f"school:{self.running.pk}", "length": "1", "unit": "months"})
        ends = Subscription.objects.get(school=self.running).trial_ends_at
        self.assertGreater(ends, self.ends + timedelta(days=27))

    def test_a_learner_with_no_plan_yet(self):
        learner = person("solo@example.com", role="individual")
        page = self.client.get("/manage/schools-directory/0/")
        self.assertContains(page, "<th>Plan</th>", html=True)
        self.assertContains(page, f'data-trial-target="user:{learner.pk}"')
        self.client.post(self.url, {"target": f"user:{learner.pk}", "length": "7", "unit": "days", "reason": "Exam month"})
        sub = Subscription.objects.get(user=learner)
        self.assertGreater(sub.trial_ends_at, timezone.now() + timedelta(days=6))
        self.assertEqual(sub.custom_trial_reason, "Exam month")

    def test_bad_values_and_non_staff_are_refused(self):
        before = Subscription.objects.get(school=self.ended).trial_ends_at
        page = self.client.post(self.url, {"target": f"school:{self.ended.pk}", "length": "0", "unit": "days"}, follow=True)
        self.assertContains(page, "Choose how much trial to add")
        self.client.post(self.url, {"target": f"school:{self.ended.pk}", "length": "5", "unit": "years"})
        self.assertEqual(Subscription.objects.get(school=self.ended).trial_ends_at, before)
        self.client.force_login(person("head@example.com", role="school_admin", school=self.ended))
        self.client.post(self.url, {"target": f"school:{self.ended.pk}", "length": "30", "unit": "days"})
        self.assertEqual(Subscription.objects.get(school=self.ended).trial_ends_at, before)
