"""A school's "Plan ends on" (November 2026): staff set the day a school's
access ends directly, to correct it, instead of giving the plan again (which
adds its length on top). The plan and the payment records stay as they are."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Payment, Plan, Subscription
from apps.schools.models import School

User = get_user_model()


class PlanEndTests(TestCase):
    def setUp(self):
        self.plan = Plan.objects.create(name="Termly", audience="school", price=Decimal("90000"), duration_days=122,
                                        min_units=11, max_units=20)
        self.school = School.objects.create(name="Glendale", email="g@example.com")
        self.wrong = timezone.now() + timedelta(days=600)
        Subscription.objects.update_or_create(school=self.school, defaults={"plan": self.plan, "paid_until": self.wrong})
        User.objects.create_user("head@example.com", "pw-12345678", first_name="Head", role="school_admin",
                                 school=self.school)                     # its sign-in, as every school has
        self.staff = User.objects.create_superuser("boss@example.com", "pw-12345678", first_name="Boss")
        self.client.force_login(self.staff)
        self.url = f"/manage/schools/{self.school.pk}/"

    def post(self, **changes):
        form = self.client.get(self.url).context["form"]
        data = {}
        for name in form.fields:
            value = form[name].value()
            if value is None or value is False:
                continue
            data[name] = value
        data.update(changes)
        return self.client.post(self.url, data, follow=True)

    def test_the_end_date_is_set_directly(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Plan ends on")
        self.assertContains(page, f"Now: {timezone.localtime(self.wrong):%d %B %Y}")
        payments = Payment.objects.count()
        answer = self.post(plan_ends_on="2028-05-31")
        self.assertContains(answer, "access now ends on 31 May 2028")
        subscription = Subscription.objects.get(school=self.school)
        ends = timezone.localtime(subscription.paid_until)
        self.assertEqual((ends.date(), ends.hour, ends.minute), (date(2028, 5, 31), 23, 59))   # end of that day
        self.assertEqual(subscription.plan, self.plan)                                          # plan unchanged
        self.assertEqual(Payment.objects.count(), payments)                                    # no payment made
        log = LogEntry.objects.filter(object_repr=self.school.name).latest("action_time")
        self.assertIn("Plan end date set to 31 May 2028", log.change_message)
        self.assertIn("was", log.change_message)

    def test_left_empty_nothing_changes(self):
        self.post(name="Glendale British Fountain")
        self.assertEqual(Subscription.objects.get(school=self.school).paid_until, self.wrong)

    def test_not_with_a_new_plan_in_the_same_save(self):
        answer = self.post(plan_ends_on="2028-05-31", grant_plan=self.plan.pk)
        self.assertContains(answer, "not both at once")
        self.assertEqual(Subscription.objects.get(school=self.school).paid_until, self.wrong)

    def test_not_in_the_past_and_not_without_a_plan(self):
        answer = self.post(plan_ends_on=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertContains(answer, "Choose today or a later day")
        Subscription.objects.filter(school=self.school).update(plan=None)
        answer = self.post(plan_ends_on="2028-05-31")
        self.assertContains(answer, "no plan yet")
