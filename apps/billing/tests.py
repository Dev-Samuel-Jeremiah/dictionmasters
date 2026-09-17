import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.schools.models import AccessCode, School

from . import services
from .access import has_access, plans_for, start_trial, subscription_for
from .models import BillingSettings, Payment, Plan, Subscription

SECRET = "sk_test_unit"
PASSWORD = "x-Strong-pass-1"
PAYSTACK_PAGE = {"authorization_url": "https://checkout.paystack.com/abc"}


def verified(payment, **overrides):
    data = {"status": "success", "reference": payment.reference, "amount": payment.amount,
            "currency": "NGN", "channel": "card", "paid_at": "2026-09-17T10:00:00.000Z",
            "gateway_response": "Approved"}
    data.update(overrides)
    return data


def make_user(email, role, **extra):
    return User.objects.create_user(email=email, password=PASSWORD, first_name="Test", role=role, **extra)


@override_settings(PAYSTACK_SECRET_KEY=SECRET, PAYSTACK_PUBLIC_KEY="pk_test_unit")
class BillingTests(TestCase):
    def setUp(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"trial_days": 7, "paywall_enabled": True})
        Plan.objects.all().delete()
        self.monthly = Plan.objects.create(name="Monthly", audience="individual", price=Decimal("2500"), duration_days=30)
        self.tier5 = Plan.objects.create(name="Termly", audience="school", price=Decimal("48000"), duration_days=122, min_units=1, max_units=5)
        self.tier10 = Plan.objects.create(name="Termly", audience="school", price=Decimal("72000"), duration_days=122, min_units=6, max_units=10)
        self.band50 = Plan.objects.create(name="Termly", audience="student", price=Decimal("2000"), duration_days=122, min_units=1, max_units=50)
        self.band100 = Plan.objects.create(name="Termly", audience="student", price=Decimal("1800"), duration_days=122, min_units=51, max_units=100)
        self.adult = make_user("adult@example.com", User.Role.INDIVIDUAL)
        self.school = School.objects.create(name="Bright Future", email="admin@bright.test")
        self.admin = make_user("admin@bright.test", User.Role.SCHOOL_ADMIN, school=self.school)

    def pay(self, user, plan):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(user, plan, callback_url="x", cancel_url="y")
        services.fulfil(payment.reference, verified(payment))
        return payment

    # ---- trial -------------------------------------------------------------

    def test_trial_only_starts_when_chosen_and_only_once(self):
        sub = subscription_for(self.adult)
        self.assertIsNone(sub.trial_ends_at)
        self.assertFalse(has_access(self.adult))
        self.assertTrue(start_trial(self.adult))
        self.assertTrue(has_access(self.adult))
        self.assertEqual(subscription_for(self.adult).days_left(), 7)
        self.assertFalse(start_trial(self.adult))

    def test_tools_lock_without_access_but_dashboard_stays_open(self):
        self.client.force_login(self.adult)
        locked = self.client.get("/echospell/")
        self.assertRedirects(locked, f"{reverse('billing:account')}?next=%2Fechospell%2F", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)
        self.assertEqual(self.client.post("/echospell/card-position/", {"lesson": 1}).status_code, 402)

    def test_paywall_switch_opens_everything(self):
        BillingSettings.objects.filter(pk=1).update(paywall_enabled=False)
        self.assertTrue(has_access(self.adult))

    def test_staff_are_never_billed(self):
        staff = make_user("staff@example.com", User.Role.INDIVIDUAL, is_staff=True)
        self.assertIsNone(subscription_for(staff))
        self.assertTrue(has_access(staff))

    # ---- registering: trial or pay now -------------------------------------

    def adult_form(self, **extra):
        return {"first_name": "Ada", "email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD, **extra}

    def test_register_with_free_trial(self):
        response = self.client.post(reverse("accounts:register_individual"), self.adult_form(start="trial"))
        self.assertRedirects(response, reverse("accounts:dashboard"), fetch_redirect_response=False)
        self.assertEqual(User.objects.get(email="new@example.com").subscription.state(), Subscription.STATE_TRIAL)

    def test_register_and_pay_now_goes_to_paystack_without_a_trial(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            response = self.client.post(reverse("accounts:register_individual"),
                                        self.adult_form(start="pay", plan=self.monthly.slug))
        self.assertRedirects(response, PAYSTACK_PAGE["authorization_url"], fetch_redirect_response=False)
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 250000)
        user = User.objects.get(email="new@example.com")
        self.assertIsNone(user.subscription.trial_ends_at)
        # Didn't finish paying? The trial is still there to start later.
        self.client.force_login(user)
        self.client.post(reverse("billing:trial"))
        user.subscription.refresh_from_db()
        self.assertIsNotNone(user.subscription.trial_ends_at)

    def test_pay_now_needs_a_plan(self):
        response = self.client.post(reverse("accounts:register_individual"), self.adult_form(start="pay"))
        self.assertContains(response, "Choose the plan")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    # ---- students ----------------------------------------------------------

    def student_form(self, email, **extra):
        return {"school_code": self.school.code, "level": "Level 1", "first_name": "Chidi", "email": email,
                "password1": PASSWORD, "password2": PASSWORD, **extra}

    def test_student_signs_up_with_school_code_and_pays_the_band_rate(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            response = self.client.post(reverse("accounts:register_student"),
                                        self.student_form("kid@bright.test", start="pay", plan="Termly"))
        self.assertRedirects(response, PAYSTACK_PAGE["authorization_url"], fetch_redirect_response=False)
        student = User.objects.get(email="kid@bright.test")
        self.assertEqual((student.role, student.school, student.level), (User.Role.STUDENT, self.school, "Level 1"))
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 200000)       # 1–50 children: ₦2,000
        self.assertEqual(student.subscription.user, student)                 # pays for themself

    def test_bigger_school_enrolment_lowers_the_price_per_child(self):
        for n in range(50):
            make_user(f"kid{n}@bright.test", User.Role.STUDENT, school=self.school)
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            self.client.post(reverse("accounts:register_student"),
                             self.student_form("kid51@bright.test", start="pay", plan="Termly"))
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 180000)       # 51st child: ₦1,800

    def test_student_price_lookup_by_code(self):
        response = self.client.get(reverse("billing:student_prices"), {"code": self.school.code})
        self.assertEqual(response.json()["options"], [{"period": "Termly", "price": "₦2,000", "text": "per term"}])
        self.assertFalse(self.client.get(reverse("billing:student_prices"), {"code": "DM-NOPE"}).json()["found"])

    def test_students_cannot_join_with_access_codes_or_pay_through_school(self):
        code = AccessCode.objects.create(school=self.school, role="student", level="Level 1", created_by=self.admin)
        response = self.client.post(reverse("accounts:join_with_code"), {
            "code": code.code, "first_name": "Kid", "email": "sneaky@bright.test", "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertContains(response, "Students now join with their school")
        # A paid school plan doesn't cover students.
        start_trial(self.admin)
        self.pay(self.admin, self.tier5)
        student = make_user("kid@bright.test", User.Role.STUDENT, school=self.school)
        self.assertFalse(has_access(student))

    # ---- schools -----------------------------------------------------------

    def test_school_plan_covers_admin_and_teachers(self):
        teacher = make_user("t@bright.test", User.Role.TEACHER, school=self.school)
        self.assertFalse(has_access(teacher))
        with self.assertRaises(services.CheckoutError):
            services.start_checkout(teacher, self.tier5, callback_url="x", cancel_url="y")
        self.pay(self.admin, self.tier5)
        self.assertTrue(has_access(teacher))
        self.assertTrue(has_access(self.admin))

    def test_school_cannot_buy_a_tier_smaller_than_its_teachers(self):
        for n in range(6):
            make_user(f"t{n}@bright.test", User.Role.TEACHER, school=self.school)
        offered = {plan.pk: ok for plan, ok, _why in plans_for(self.admin)}
        self.assertEqual(offered, {self.tier5.pk: False, self.tier10.pk: True})
        with self.assertRaises(services.CheckoutError):
            services.start_checkout(self.admin, self.tier5, callback_url="x", cancel_url="y")

    def test_teachers_stop_joining_when_the_tier_is_full(self):
        self.pay(self.admin, self.tier5)
        for n in range(5):
            make_user(f"t{n}@bright.test", User.Role.TEACHER, school=self.school)
        code = AccessCode.objects.create(school=self.school, role="teacher", level="Level 1", created_by=self.admin)
        response = self.client.post(reverse("accounts:join_with_code"), {
            "code": code.code, "first_name": "Late", "email": "late@bright.test", "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertContains(response, "reached the number of teachers its plan allows")

    # ---- paying ------------------------------------------------------------

    def test_payment_during_trial_starts_after_the_trial_and_counts_once(self):
        start_trial(self.adult)
        sub = subscription_for(self.adult)
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(self.adult, self.monthly, callback_url="x", cancel_url="y")
        services.fulfil(payment.reference, verified(payment))
        services.fulfil(payment.reference, verified(payment))
        sub.refresh_from_db()
        self.assertEqual(sub.paid_until, sub.trial_ends_at + timedelta(days=30))

    def test_wrong_amount_never_grants_access(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(self.adult, self.monthly, callback_url="x", cancel_url="y")
        services.fulfil(payment.reference, verified(payment, amount=100))
        self.assertIsNone(subscription_for(self.adult).paid_until)
        self.assertEqual(Payment.objects.get().status, Payment.STATUS_FAILED)

    def test_callback_verifies_with_paystack_then_shows_receipt(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(self.adult, self.monthly, callback_url="x", cancel_url="y")
        self.client.force_login(self.adult)
        with mock.patch("apps.billing.paystack.verify", return_value=verified(payment)) as verify:
            response = self.client.get(reverse("billing:callback"), {"reference": payment.reference})
        verify.assert_called_once_with(payment.reference)
        self.assertRedirects(response, reverse("billing:receipt", args=[payment.reference]), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("billing:receipt", args=[payment.reference])).status_code, 200)
        other = make_user("other@example.com", User.Role.INDIVIDUAL)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("billing:receipt", args=[payment.reference])).status_code, 404)

    def post_webhook(self, body, signature=None):
        raw = json.dumps(body).encode()
        signature = signature if signature is not None else hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
        return self.client.post(reverse("billing:webhook"), raw, content_type="application/json",
                                HTTP_X_PAYSTACK_SIGNATURE=signature)

    def test_webhook_checks_signature_and_confirms_with_paystack(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(self.adult, self.monthly, callback_url="x", cancel_url="y")
        body = {"event": "charge.success", "data": {"reference": payment.reference}}
        self.assertEqual(self.post_webhook(body, signature="forged").status_code, 400)
        self.assertEqual(Payment.objects.get().status, Payment.STATUS_PENDING)
        with mock.patch("apps.billing.paystack.verify", return_value=verified(payment)) as verify:
            self.assertEqual(self.post_webhook(body).status_code, 200)
        verify.assert_called_once_with(payment.reference)
        self.assertEqual(Payment.objects.get().status, Payment.STATUS_SUCCESS)

    def test_no_free_trial_after_paying(self):
        self.pay(self.adult, self.monthly)
        self.client.force_login(self.adult)
        page = self.client.get(reverse("billing:account"))
        self.assertNotContains(page, "Start my 7-day free trial")
        self.client.post(reverse("billing:trial"))
        self.assertIsNone(subscription_for(self.adult).trial_ends_at)

    def test_renewal_opens_in_the_last_five_days_and_early_renewal_adds_on(self):
        self.pay(self.adult, self.monthly)                      # 30 days
        self.client.force_login(self.adult)
        page = self.client.get(reverse("billing:account")).content.decode()
        self.assertIn("Renew early", page)
        self.assertNotIn("Renew now", page)
        sub = subscription_for(self.adult)
        first_end = sub.paid_until
        self.pay(self.adult, self.monthly)                      # renew early
        sub.refresh_from_db()
        self.assertEqual(sub.paid_until, first_end + timedelta(days=30))

        sub.paid_until = timezone.now() + timedelta(days=4)
        sub.save()
        page = self.client.get(reverse("billing:account")).content.decode()
        self.assertIn("Renew now", page)
        self.assertIn("Your plan ends in <strong>4 days</strong>", self.client.get(reverse("accounts:dashboard")).content.decode())

    # ---- pages -------------------------------------------------------------

    def test_pages_render_for_each_kind_of_account(self):
        self.assertContains(self.client.get(reverse("billing:pricing")), "₦48,000")
        student = make_user("kid@bright.test", User.Role.STUDENT, school=self.school)
        teacher = make_user("t@bright.test", User.Role.TEACHER, school=self.school)
        for user, expect in ((self.adult, "₦2,500"), (self.admin, "₦72,000"), (student, "₦2,000"), (teacher, "Your school looks after this")):
            self.client.force_login(user)
            self.assertContains(self.client.get(reverse("billing:account")), expect)
        for name in ("register_individual", "register_school", "register_student"):
            self.client.logout()
            self.assertContains(self.client.get(reverse(f"accounts:{name}")), "How would you like to start?")
