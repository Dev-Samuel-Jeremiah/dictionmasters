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
from .models import BillingSettings, Payment, Plan, PromoCode, Subscription

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

    def expire(self, user):
        sub = subscription_for(user)
        sub.trial_ends_at = timezone.now() - timedelta(minutes=1)
        sub.save()
        return sub

    def test_every_account_starts_on_its_trial_and_gets_it_once(self):
        sub = subscription_for(self.adult)
        self.assertEqual(sub.state(), Subscription.STATE_TRIAL)
        self.assertEqual(sub.days_left(), 7)
        self.assertTrue(has_access(self.adult))
        self.expire(self.adult)
        self.assertFalse(start_trial(self.adult))
        self.assertFalse(has_access(self.adult))

    def test_no_account_reaches_the_dashboard_on_neither(self):
        BillingSettings.objects.filter(pk=1).update(trial_days=0)
        fresh = make_user("fresh@example.com", User.Role.INDIVIDUAL)
        self.client.force_login(fresh)
        self.assertRedirects(self.client.get(reverse("accounts:dashboard")), reverse("billing:account"), fetch_redirect_response=False)

    def test_tools_lock_after_the_trial_but_dashboard_stays_open(self):
        self.expire(self.adult)
        self.client.force_login(self.adult)
        locked = self.client.get("/echospell/")
        self.assertRedirects(locked, f"{reverse('billing:account')}?next=%2Fechospell%2F", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 200)
        self.assertEqual(self.client.post("/echospell/card-position/", {"lesson": 1}).status_code, 402)

    def test_paywall_switch_opens_everything(self):
        self.expire(self.adult)
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

    def test_pay_now_that_fails_leaves_the_trial_running(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            response = self.client.post(reverse("accounts:register_individual"),
                                        self.adult_form(start="pay", plan=self.monthly.slug))
        self.assertRedirects(response, PAYSTACK_PAGE["authorization_url"], fetch_redirect_response=False)
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 250000)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.subscription.state(), Subscription.STATE_TRIAL)   # counting already
        payment = Payment.objects.get(payer=user)
        with mock.patch("apps.billing.paystack.verify", return_value=verified(payment, status="failed")):
            response = self.client.get(reverse("billing:callback"), {"reference": payment.reference}, follow=True)
        self.assertContains(response, "Your free trial is active with 7 days left")
        # Cancelling on Paystack's page says the same.
        response = self.client.get(reverse("billing:callback"), {"cancelled": "1"}, follow=True)
        self.assertContains(response, "You cancelled the payment")

    def test_pay_now_that_succeeds_replaces_the_trial(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            self.client.post(reverse("accounts:register_individual"), self.adult_form(start="pay", plan=self.monthly.slug))
        user = User.objects.get(email="new@example.com")
        payment = Payment.objects.get(payer=user)
        before = timezone.now()
        services.fulfil(payment.reference, verified(payment))
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.state(), Subscription.STATE_ACTIVE)
        self.assertLessEqual(sub.trial_ends_at, timezone.now())                  # trial over
        self.assertAlmostEqual(sub.paid_until, before + timedelta(days=30), delta=timedelta(minutes=1))

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
        # A paid school plan doesn't cover students: they have their own.
        self.pay(self.admin, self.tier5)
        student = make_user("kid@bright.test", User.Role.STUDENT, school=self.school)
        self.assertEqual(subscription_for(student).user, student)
        self.expire(student)
        self.assertFalse(has_access(student))

    # ---- schools -----------------------------------------------------------

    def test_school_plan_covers_admin_and_teachers(self):
        teacher = make_user("t@bright.test", User.Role.TEACHER, school=self.school)
        self.expire(self.admin)                                  # the school's trial is over
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

    def test_a_payment_counts_once(self):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE):
            payment = services.start_checkout(self.adult, self.monthly, callback_url="x", cancel_url="y")
        services.fulfil(payment.reference, verified(payment))
        first = subscription_for(self.adult).paid_until
        services.fulfil(payment.reference, verified(payment))
        self.assertEqual(subscription_for(self.adult).paid_until, first)

    def test_wrong_amount_never_grants_access(self):
        self.expire(self.adult)
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
        sub = subscription_for(self.adult)
        sub.trial_ends_at = None                                  # even if the trial were somehow cleared
        sub.save()
        self.assertEqual(subscription_for(self.adult).trial_ends_at, None)
        self.assertEqual(subscription_for(self.adult).state(), Subscription.STATE_ACTIVE)
        page = self.client.get(reverse("billing:account")).content.decode()
        self.assertNotIn("Start my 7-day free trial", page)      # no trial button once paid
        self.assertIn("Active until", page)

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


@override_settings(PAYSTACK_SECRET_KEY=SECRET, PAYSTACK_PUBLIC_KEY="pk_test_unit")
class PromoCodeTests(TestCase):
    """Codes like JDM201: how much they take off, and the limits on them."""

    def setUp(self):
        BillingSettings.objects.update_or_create(pk=1, defaults={"trial_days": 7, "paywall_enabled": True})
        Plan.objects.all().delete()
        self.monthly = Plan.objects.create(name="Monthly", audience="individual", price=Decimal("2500"), duration_days=30)
        self.yearly = Plan.objects.create(name="Yearly", audience="individual", price=Decimal("24000"), duration_days=365)
        self.code = PromoCode.objects.create(code="JDM201", kind=PromoCode.PERCENT, value=Decimal("25"), max_uses=2)
        self.adult = make_user("adult@example.com", User.Role.INDIVIDUAL)
        start_trial(self.adult)

    def buy(self, user, plan, promo=None):
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            payment = services.start_checkout(user, plan, promo=promo, callback_url="x", cancel_url="y")
        return payment, init

    def test_a_code_is_made_in_the_house_style(self):
        made = PromoCode.objects.create(value=Decimal("10"))
        self.assertRegex(made.code, r"^JDM\d{3}$")
        self.assertNotEqual(made.code, self.code.code)
        # A typed code is tidied up.
        typed = PromoCode.objects.create(code=" jdm-flyer ", value=Decimal("10"))
        self.assertEqual(typed.code, "JDM-FLYER")

    def test_a_percentage_and_a_flat_amount_come_off(self):
        self.assertEqual(self.code.discount_kobo(250000), 62500)
        self.assertEqual(self.code.price_after(250000), 187500)
        flat = PromoCode.objects.create(code="JDM500", kind=PromoCode.AMOUNT, value=Decimal("500"))
        self.assertEqual(flat.price_after(250000), 200000)
        # Never more than the price.
        self.assertEqual(PromoCode.objects.create(code="BIG", kind=PromoCode.AMOUNT,
                                                  value=Decimal("9000")).price_after(250000), 0)

    def test_paying_with_a_code_charges_the_lower_price(self):
        payment, init = self.buy(self.adult, self.monthly, self.code)
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 187500)
        self.assertEqual((payment.amount, payment.discount, payment.promo_code), (187500, 62500, "JDM201"))
        services.fulfil(payment.reference, verified(payment))
        self.assertTrue(has_access(self.adult))
        self.assertEqual(self.code.used, 1)

    def test_the_number_of_uses_runs_out(self):
        self.buy(self.adult, self.monthly, self.code)
        second = make_user("two@example.com", User.Role.INDIVIDUAL)
        start_trial(second)
        self.buy(second, self.monthly, self.code)
        third = make_user("three@example.com", User.Role.INDIVIDUAL)
        start_trial(third)
        self.assertEqual(self.code.uses_left, 0)
        self.assertEqual(self.code.state, "All used")
        with self.assertRaises(services.CheckoutError):
            self.buy(third, self.monthly, self.code)
        _, refusal = services.find_promo("JDM201", third, self.monthly)
        self.assertEqual(refusal, "That code has been used up.")

    def test_an_account_uses_a_code_once(self):
        self.buy(self.adult, self.monthly, self.code)
        _, refusal = services.find_promo("JDM201", self.adult, self.monthly)
        self.assertEqual(refusal, "You've already used that code.")

    def test_dates_and_plans_and_the_off_switch(self):
        later = PromoCode.objects.create(code="SOON", value=Decimal("10"),
                                         starts_at=timezone.now() + timedelta(days=1))
        self.assertEqual(services.find_promo("SOON", self.adult, self.monthly)[1], "That code isn't active yet.")
        gone = PromoCode.objects.create(code="GONE", value=Decimal("10"),
                                        expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.find_promo("GONE", self.adult, self.monthly)[1], "That code has expired.")
        self.assertEqual(gone.state, "Expired")
        off = PromoCode.objects.create(code="OFF", value=Decimal("10"), is_active=False)
        self.assertEqual(services.find_promo("OFF", self.adult, self.monthly)[1], "That code isn't available.")
        only_yearly = PromoCode.objects.create(code="YEAR", value=Decimal("10"))
        only_yearly.plans.add(self.yearly)
        self.assertEqual(services.find_promo("YEAR", self.adult, self.monthly)[1],
                         "That code doesn't apply to this plan.")
        self.assertIsNone(services.find_promo("YEAR", self.adult, self.yearly)[1])
        self.assertEqual(services.find_promo("NOPE", self.adult, self.monthly)[1],
                         "We don't know that code. Please check it and try again.")
        self.assertEqual(later.uses_left, None)

    def test_a_code_that_covers_the_whole_price_needs_no_payment(self):
        free = PromoCode.objects.create(code="JDMFREE", kind=PromoCode.PERCENT, value=Decimal("100"))
        with mock.patch("apps.billing.paystack.initialize") as init:
            payment = services.start_checkout(self.adult, self.monthly, promo=free,
                                              callback_url="x", cancel_url="y")
        init.assert_not_called()
        self.assertTrue(payment.is_paid)
        self.assertEqual((payment.amount, payment.discount, payment.channel), (0, 250000, "promo"))
        self.assertTrue(has_access(self.adult))
        self.assertAlmostEqual(subscription_for(self.adult).paid_until, timezone.now() + timedelta(days=30),
                               delta=timedelta(minutes=1))

    def test_a_payment_that_never_completes_frees_the_code_again(self):
        payment, _ = self.buy(self.adult, self.monthly, self.code)
        self.assertEqual(self.code.used, 1)
        services.fulfil(payment.reference, verified(payment, status="abandoned"))
        self.assertEqual(self.code.used, 0)

    def test_registering_with_a_code(self):
        form = {"first_name": "Ada", "email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD,
                "start": "pay", "plan": self.monthly.slug, "promo_code": "jdm201"}
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            response = self.client.post(reverse("accounts:register_individual"), form)
        self.assertRedirects(response, PAYSTACK_PAGE["authorization_url"], fetch_redirect_response=False)
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 187500)
        self.assertEqual(Payment.objects.get(email="new@example.com").promo_code, "JDM201")

    def test_registering_with_a_code_that_is_wrong(self):
        form = {"first_name": "Ada", "email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD,
                "start": "pay", "plan": self.monthly.slug, "promo_code": "NOPE"}
        response = self.client.post(reverse("accounts:register_individual"), form)
        self.assertContains(response, "We don&#x27;t know that code")
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_applying_a_code_on_the_billing_page_then_paying(self):
        self.client.force_login(self.adult)
        response = self.client.post(reverse("billing:promo"), {"code": "jdm201"}, follow=True)
        self.assertContains(response, "JDM201 applied")
        page = self.client.get(reverse("billing:account"))
        self.assertContains(page, "₦1,875")                       # 25% off ₦2,500
        with mock.patch("apps.billing.paystack.initialize", return_value=PAYSTACK_PAGE) as init:
            self.client.post(reverse("billing:checkout", args=[self.monthly.slug]))
        self.assertEqual(init.call_args.kwargs["amount_kobo"], 187500)
        # The code is spent, so the page goes back to full price.
        self.assertNotContains(self.client.get(reverse("billing:account")), "JDM201 applied")

    def test_taking_a_code_off_again(self):
        self.client.force_login(self.adult)
        self.client.post(reverse("billing:promo"), {"code": "JDM201"})
        response = self.client.post(reverse("billing:promo"), {"remove": "1"}, follow=True)
        self.assertContains(response, "Promo code removed")
        self.assertNotContains(self.client.get(reverse("billing:account")), "JDM201 applied")

    def test_the_control_room_makes_and_lists_codes(self):
        staff = make_user("staff@example.com", User.Role.INDIVIDUAL, is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        listing = self.client.get("/manage/promo-codes/")
        self.assertContains(listing, "JDM201")
        self.assertContains(listing, "25% off")
        self.client.post("/manage/promo-codes/new/", {
            "code": "", "note": "School fair", "kind": "amount", "value": "1000",
            "max_uses": 50, "once_per_account": "on", "is_active": "on",
        })
        made = PromoCode.objects.exclude(pk=self.code.pk).get()
        self.assertRegex(made.code, r"^JDM\d{3}$")
        self.assertEqual((made.kind, made.value, made.max_uses), ("amount", Decimal("1000"), 50))
        self.buy(self.adult, self.monthly, self.code)
        self.assertContains(self.client.get("/manage/promo-uses/"), "JDM201")
