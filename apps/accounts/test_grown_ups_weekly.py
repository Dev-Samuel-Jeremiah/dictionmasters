"""Phase 4: For grown-ups behind a PIN, the weekly summary and emails, and
the teacher's "Needs help" list."""

import time

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.echospell.models import Activity, ActivityAttempt, Group, GroupProgress, Level
from apps.schools.models import School

from . import grown_ups
from .models import INTERNAL_EMAIL_DOMAIN, GrownUpSettings
from .weekly import learner_summary, send_weekly

User = get_user_model()
URL = "/accounts/grown-ups/"


def make(email, **extra):
    return User.objects.create_user(email, "mango-river-47", first_name=email.split("@")[0].title(), **extra)


class PinTests(TestCase):
    def setUp(self):
        self.parent = make("parent@example.com")
        self.client.force_login(self.parent)

    def set_pin(self, pin="2468"):
        return self.client.post(URL, {"action": "set", "pin": pin, "pin2": pin})

    def forget_unlock(self):
        session = self.client.session
        session[grown_ups.SESSION_KEY] = {"user": self.parent.pk, "until": time.time() - 1}
        session.save()

    def test_the_first_visit_sets_a_pin(self):
        page = self.client.get(URL)
        self.assertContains(page, "Choose a 4-number PIN")
        self.assertNotContains(page, "Use the simple home")
        self.assertContains(self.client.post(URL, {"action": "set", "pin": "12", "pin2": "12"}), "Choose 4 numbers")
        self.assertContains(self.client.post(URL, {"action": "set", "pin": "1234", "pin2": "4321"}), "The two PINs")
        self.assertRedirects(self.set_pin(), URL)
        page = self.client.get(URL)
        self.assertContains(page, "Use the simple home")
        self.assertContains(page, "data-week-summary")
        self.assertNotIn("2468", GrownUpSettings.objects.get(user=self.parent).pin_hash)

    def test_the_pin_is_asked_for_again_once_the_unlock_runs_out(self):
        self.set_pin()
        self.forget_unlock()
        page = self.client.get(URL)
        self.assertContains(page, "Enter the grown-ups' PIN")
        self.assertContains(self.client.post(URL, {"action": "unlock", "pin": "1111"}), "not the PIN")
        self.assertRedirects(self.client.post(URL, {"action": "unlock", "pin": "2468"}), URL)
        self.assertContains(self.client.get(URL), "Use the simple home")

    def test_five_wrong_pins_shut_pin_entry_for_a_while(self):
        self.set_pin()
        self.forget_unlock()
        for _ in range(grown_ups.MAX_TRIES):
            self.client.post(URL, {"action": "unlock", "pin": "0000"})
        page = self.client.post(URL, {"action": "unlock", "pin": "2468"})
        self.assertContains(page, "Too many wrong PINs")
        self.assertNotContains(self.client.get(URL), "Use the simple home")

    def test_a_forgotten_pin_is_replaced_with_the_account_password(self):
        self.set_pin()
        self.forget_unlock()
        self.assertContains(self.client.get(URL + "?forgot=1"), "The account's password")
        wrong = self.client.post(URL, {"action": "reset", "password": "nope", "pin": "1357"})
        self.assertContains(wrong, "That password")
        self.assertRedirects(self.client.post(URL, {"action": "reset", "password": "mango-river-47", "pin": "1357"}), URL)
        self.forget_unlock()
        self.assertRedirects(self.client.post(URL, {"action": "unlock", "pin": "1357"}), URL)

    def test_a_child_cannot_switch_the_simple_home_off_without_the_pin(self):
        self.set_pin()
        self.client.post(URL, {"action": "home", "simple_home": "on"})
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.simple_home)
        self.forget_unlock()
        self.client.post(URL, {"action": "home"})
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.simple_home)

    def test_lock_and_go_home(self):
        self.set_pin()
        self.assertRedirects(self.client.post(URL, {"action": "lock"}), "/accounts/dashboard/",
                             fetch_redirect_response=False)
        self.assertContains(self.client.get(URL), "Enter the grown-ups' PIN")

    def test_an_unlock_belongs_to_one_account(self):
        self.set_pin()
        sibling = make("sibling@example.com")
        GrownUpSettings.objects.create(user=sibling, pin_hash=GrownUpSettings.objects.get(user=self.parent).pin_hash)
        session = self.client.session
        unlocked = session[grown_ups.SESSION_KEY]
        self.client.force_login(sibling)
        session = self.client.session
        session[grown_ups.SESSION_KEY] = unlocked
        session.save()
        self.assertContains(self.client.get(URL), "Enter the grown-ups' PIN")

    def test_teachers_have_no_pin(self):
        self.client.force_login(make("teach@example.com", role="teacher"))
        self.assertContains(self.client.get(URL), "data-week-summary")

    def test_the_weekly_email_can_be_switched_off(self):
        self.set_pin()
        self.client.post(URL, {"action": "weekly"})
        self.assertFalse(GrownUpSettings.objects.get(user=self.parent).weekly_email)


class StuckTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.teacher = make("teach@example.com", role="teacher", school=self.school, level="Level 2")
        self.ada = make("ada@example.com", role="student", school=self.school, level="Level 2")
        level, _ = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})
        group = Group.objects.create(level=level, number=9, slug="stuck-9")
        self.activity = Activity.objects.create(group=group, kind="dictation", title="Spell it", pass_mark=80)
        GroupProgress.objects.create(user=self.ada, group=group)        # active this week, so not quiet

    def fail(self, times):
        for _ in range(times):
            ActivityAttempt.objects.create(user=self.ada, activity=self.activity, status="marked", percent=20)

    def test_three_failed_tries_without_a_pass_is_stuck(self):
        self.fail(2)
        self.assertEqual(learner_summary(self.ada)["row"]["stuck_on"], [])
        self.fail(1)
        row = learner_summary(self.ada)["row"]
        self.assertEqual(row["stuck_on"], [{"title": "Spell it", "tries": 3}])
        self.assertTrue(row["needs_help"])
        ActivityAttempt.objects.create(user=self.ada, activity=self.activity, status="marked", percent=90, passed=True)
        self.assertFalse(learner_summary(self.ada)["row"]["needs_help"])

    def test_the_teacher_sees_who_needs_help(self):
        self.fail(3)
        self.client.force_login(self.teacher)
        page = self.client.get("/school/class/")
        self.assertContains(page, "data-needs-help")
        self.assertContains(page, "Stuck on Spell it: 3 tries, not passed yet.")
        self.assertContains(self.client.get("/accounts/dashboard/"), "<b>1</b>needs help", html=False)

    def test_the_summary_says_so(self):
        self.fail(3)
        titles = dict(learner_summary(self.ada)["lines"])
        self.assertIn("Spell it (3 tries)", titles["Could use a hand with"])
        self.assertEqual(titles["Lessons finished"], "1 EchoSpell group.")


class WeeklyEmailTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.adult = make("adult@example.com")
        self.off = make("off@example.com")
        GrownUpSettings.objects.create(user=self.off, weekly_email=False)
        self.no_inbox = make(f"pupil@{INTERNAL_EMAIL_DOMAIN}", role="student", school=self.school, level="Level 2")
        self.teacher = make("teach@example.com", role="teacher", school=self.school, level="Level 2")

    def quiet(self, pupil):
        """Active once, ten days ago: quiet, so on the teacher's list."""
        from datetime import timedelta

        from django.utils import timezone

        level = Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})[0]
        done = GroupProgress.objects.create(user=pupil, group=Group.objects.create(level=level, number=4, slug="q4"))
        GroupProgress.objects.filter(pk=done.pk).update(completed_at=timezone.now() - timedelta(days=10))

    def test_who_gets_what(self):
        self.quiet(self.no_inbox)
        call_command("send_weekly_summaries")
        to = sorted(m.to[0] for m in mail.outbox)
        # The quiet pupil makes the teacher's "Needs help" email; the pupil
        # has no inbox, and "off" switched it off. A pupil who never started
        # isn't "quiet", so wouldn't.
        self.assertEqual(to, ["adult@example.com", "teach@example.com"])
        teacher_mail = next(m for m in mail.outbox if m.to == ["teach@example.com"])
        self.assertIn("Pupil", teacher_mail.body)
        self.assertIn("Nothing done in the last 7 days", teacher_mail.body)

    def test_a_week_is_never_sent_twice(self):
        self.quiet(self.no_inbox)
        call_command("send_weekly_summaries")
        sent = len(mail.outbox)
        call_command("send_weekly_summaries")
        self.assertEqual(len(mail.outbox), sent)

    def test_a_dry_run_sends_nothing(self):
        call_command("send_weekly_summaries", "--dry-run", stdout=open("/dev/null", "w"))
        self.assertEqual(mail.outbox, [])
        self.assertFalse(GrownUpSettings.objects.exclude(last_summary_at=None).exists())

    def test_a_teacher_with_nobody_stuck_gets_nothing(self):
        GroupProgress.objects.create(user=self.no_inbox, group=Group.objects.create(
            level=Level.objects.update_or_create(name="Level 2", defaults={"is_published": True})[0], number=3, slug="w3"))
        call_command("send_weekly_summaries")
        self.assertNotIn(["teach@example.com"], [m.to for m in mail.outbox])

    def test_the_cost_does_not_grow_with_the_number_of_learners(self):
        with CaptureQueriesContext(connection) as few:
            send_weekly(dry_run=True)
        for n in range(20):
            make(f"more{n}@example.com")
            make(f"kid{n}@{INTERNAL_EMAIL_DOMAIN}", role="student", school=self.school, level="Level 2")
        with CaptureQueriesContext(connection) as many:
            sent = send_weekly(dry_run=True)
        self.assertEqual(sent["learners"], 21)      # "off" switched it off; pupils have no inbox
        self.assertEqual(len(few), len(many))
