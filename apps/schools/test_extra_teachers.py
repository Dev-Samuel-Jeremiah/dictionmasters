"""Extra teachers' access (the teacher-count request of 18 November 2026,
Option A): a school's teacher limit is what its plan allows plus extra places
an admin gives, without touching its subscription, dates or payments. The
tests follow the request's own checklist."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Payment, Plan, Subscription

from .models import ExtraTeacherAccess, School

User = get_user_model()


class ExtraTeachersTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="Termly", audience="school", price=Decimal("90000"),
                                        duration_days=122, min_units=11, max_units=20)
        self.school = School.objects.create(name="Unity", email="u@example.com")
        self.paid_until = timezone.now() + timedelta(days=60)
        Subscription.objects.update_or_create(school=self.school, defaults={"plan": self.plan, "paid_until": self.paid_until})
        self.staff = User.objects.create_user("boss@example.com", "pw-12345678", first_name="Boss", is_staff=True)
        self.client.force_login(self.staff)
        self.url = f"/manage/schools-directory/{self.school.pk}/teachers/"

    def give(self, teachers=5, reason="Sent 5 more names", ends_on=""):
        return self.client.post(self.url, {"action": "give", "teachers": teachers, "reason": reason, "ends_on": ends_on},
                                follow=True)

    def teachers(self, n):
        for i in range(n):
            User.objects.create_user(f"t{i}@example.com", "pw-12345678", first_name=f"T{i}", role="teacher",
                                     school=self.school, level="Level 3")

    def test_twenty_becomes_twenty_five_with_nothing_else_changed(self):
        self.assertEqual(self.school.teacher_limit, 20)
        subscriptions, payments = Subscription.objects.count(), Payment.objects.count()
        page = self.give()
        self.school = School.objects.get(pk=self.school.pk)
        self.assertEqual(self.school.teacher_limit, 25)                     # 5 extra: 20 -> 25
        self.assertContains(page, "can now have 25 teachers")
        subscription = Subscription.objects.get(school=self.school)
        self.assertEqual(subscription.paid_until, self.paid_until)          # the term's dates stay the same
        self.assertEqual(subscription.plan, self.plan)
        self.assertEqual(Subscription.objects.count(), subscriptions)       # no new subscription
        self.assertEqual(Payment.objects.count(), payments)                 # or payment record

    def test_the_change_is_logged_with_who_when_and_why(self):
        self.give(reason="Sent 5 more names")
        grant = ExtraTeacherAccess.objects.get()
        self.assertEqual((grant.granted_by, grant.reason), (self.staff, "Sent 5 more names"))
        self.assertAlmostEqual(grant.created_at, timezone.now(), delta=timedelta(minutes=1))
        log = LogEntry.objects.get(object_repr=self.school.name)
        self.assertEqual(log.user, self.staff)
        self.assertIn("+5", log.change_message)
        self.assertIn("Sent 5 more names", log.change_message)

    def test_it_can_be_reduced_or_removed(self):
        self.give(5)
        grant = ExtraTeacherAccess.objects.get()
        self.client.post(self.url, {"action": "end", "grant": grant.pk})
        self.assertEqual(School.objects.get(pk=self.school.pk).teacher_limit, 20)
        grant.refresh_from_db()
        self.assertEqual(grant.ended_by, self.staff)                        # kept, marked ended
        self.give(3)                                                          # fewer: take back, give less
        self.assertEqual(School.objects.get(pk=self.school.pk).teacher_limit, 23)
        self.assertEqual(LogEntry.objects.filter(object_repr=self.school.name).count(), 3)

    def test_teachers_21_to_25_can_join(self):
        self.teachers(20)
        self.assertTrue(self.school.teachers_full)
        self.give(5)
        self.school = School.objects.get(pk=self.school.pk)
        self.assertFalse(self.school.teachers_full)
        self.assertEqual(self.school.teacher_places_left, 5)
        for i in range(20, 25):
            User.objects.create_user(f"t{i}@example.com", "pw-12345678", first_name=f"T{i}", role="teacher",
                                     school=self.school, level="Level 3")
        self.school = School.objects.get(pk=self.school.pk)
        self.assertTrue(self.school.teachers_full)

    def test_an_end_date_ends_it_and_renewals_keep_it_until_then(self):
        self.give(5, ends_on=(timezone.localdate() + timedelta(days=30)).isoformat())
        self.assertEqual(School.objects.get(pk=self.school.pk).teacher_limit, 25)
        # Renewed: a new paid date, the same grant.
        Subscription.objects.filter(school=self.school).update(paid_until=self.paid_until + timedelta(days=122))
        self.assertEqual(School.objects.get(pk=self.school.pk).teacher_limit, 25)
        ExtraTeacherAccess.objects.update(ends_on=timezone.localdate() - timedelta(days=1))
        self.assertEqual(School.objects.get(pk=self.school.pk).teacher_limit, 20)

    def test_teachers_allowed_on_the_school_replaces_the_plans_number(self):
        """Typed on the school's own form, higher or lower (the Sunflower case:
        a 46-50 plan, 60 typed in, still showed 50)."""
        self.assertEqual(self.school.teacher_limit, 20)
        School.objects.filter(pk=self.school.pk).update(max_teachers=60)
        school = School.objects.get(pk=self.school.pk)
        self.assertEqual(school.max_teachers, 60)
        self.assertEqual(school.teacher_limit, 60)                         # higher: it now counts
        subscription = Subscription.objects.get(school=school)
        self.assertEqual((subscription.plan, subscription.paid_until), (self.plan, self.paid_until))
        School.objects.filter(pk=school.pk).update(max_teachers=15)
        self.assertEqual(School.objects.get(pk=school.pk).teacher_limit, 15)   # lower, as before
        School.objects.filter(pk=school.pk).update(max_teachers=None)
        self.assertEqual(School.objects.get(pk=school.pk).teacher_limit, 20)   # blank: the plan's
        School.objects.filter(pk=school.pk).update(max_teachers=60)
        self.give(5)
        self.assertEqual(School.objects.get(pk=school.pk).teacher_limit, 65)   # extra places on top
        page = self.client.get(self.url)
        self.assertContains(page, "set on the school")
        self.assertContains(page, "(the plan has 20)")

    def test_it_works_for_free_and_custom_access_schools(self):
        free = School.objects.create(name="Free school", email="f@example.com", max_teachers=10)
        ExtraTeacherAccess.objects.create(school=free, teachers=4, reason="Pilot", granted_by=self.staff)
        self.assertEqual(free.teacher_limit, 14)

    def test_the_page_shows_the_three_numbers_and_refuses_bad_input(self):
        self.give(5)
        page = self.client.get(self.url)
        self.assertContains(page, "Plan teachers")
        self.assertContains(page, "Extra teachers' access")
        self.assertContains(page, "Total teachers allowed")
        self.assertContains(page, "<strong>25</strong>", html=False)
        bad = self.give(0, reason="")
        self.assertEqual(ExtraTeacherAccess.objects.count(), 1)
        self.assertContains(bad, "This field is required")
        past = self.give(2, ends_on=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertContains(past, "Choose today or a later date")

    def test_only_staff_can_give_it(self):
        head = User.objects.create_user("head@example.com", "pw-12345678", first_name="Head", role="school_admin",
                                        school=self.school)
        self.client.force_login(head)
        self.give(50)
        self.assertEqual(ExtraTeacherAccess.objects.count(), 0)
