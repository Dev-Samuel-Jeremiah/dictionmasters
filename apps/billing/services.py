"""
Starting a payment, and turning a confirmed payment into access.

A payment is only ever confirmed by asking Paystack (verify), never by
trusting the browser's return trip. Confirmation can arrive twice — the
customer's redirect and Paystack's webhook usually race — so fulfil()
locks the payment row and grants its days exactly once.
"""

import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import paystack
from .access import purchasable, start_trial, subscription_for
from .models import Payment, PromoCode, PromoRedemption, Subscription

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """This person can't buy this plan right now; the message says why."""


def find_promo(code, user=None, plan=None):
    """A promo code by what someone typed: (code, why it can't be used).
    Either may be None — a code that works comes back with no reason."""
    typed = (code or "").strip().upper().replace(" ", "")
    if not typed:
        return None, None
    promo = PromoCode.objects.filter(code__iexact=typed).first()
    if promo is None:
        return None, "We don't know that code. Please check it and try again."
    problem = promo.problem_for(user, plan)
    return (None, problem) if problem else (promo, None)


def new_reference():
    return f"DM-{uuid.uuid4().hex[:20].upper()}"


def start_checkout(user, plan, *, callback_url, cancel_url, promo=None):
    """Record a pending payment and ask Paystack for its checkout page.
    Returns the Payment, with authorization_url to send the customer to.

    A promo code takes its cut off first; one that covers the whole price
    grants the period there and then, and the Payment comes back paid,
    with nothing to pay on Paystack."""
    problem = purchasable(user, plan)
    if problem:
        raise CheckoutError(problem)
    subscription = subscription_for(user)
    if subscription is None:
        raise CheckoutError("There's no account to pay for yet.")

    amount, discount = plan.amount_kobo, 0
    if promo is not None:
        refusal = promo.problem_for(user, plan)
        if refusal:
            raise CheckoutError(refusal)
        discount = promo.discount_kobo(amount)
        amount -= discount

    if promo is not None and amount <= 0:
        return grant_free_period(user, plan, promo, discount)

    payment = Payment.objects.create(
        reference=new_reference(),
        subscription=subscription,
        plan=plan,
        payer=user,
        account_name=str(subscription),
        email=user.email,
        plan_name=(f"{plan.name} · {plan.band_label}" if plan.band_label else plan.name)[:80],
        duration_days=plan.duration_days,
        amount=amount,
        discount=discount,
        promo_code=promo.code if promo else "",
    )
    if promo is not None:
        # Held now so a limited code can't be spent twice over; released
        # again if the payment doesn't go through.
        PromoRedemption.objects.create(promo=promo, user=user, payment=payment, amount_off=discount)
    try:
        data = paystack.initialize(
            email=user.email,
            amount_kobo=payment.amount,
            reference=payment.reference,
            callback_url=callback_url,
            currency=payment.currency,
            metadata={
                "payment_reference": payment.reference,
                "plan": plan.slug,
                "account": payment.account_name,
                "cancel_action": cancel_url,
                "custom_fields": [
                    {"display_name": "Plan", "variable_name": "plan", "value": plan.name},
                    {"display_name": "Account", "variable_name": "account", "value": payment.account_name},
                ],
            },
        )
    except paystack.PaystackError as error:
        payment.status = Payment.STATUS_FAILED
        payment.gateway_response = str(error)[:255]
        payment.save(update_fields=["status", "gateway_response", "updated_at"])
        raise CheckoutError(str(error)) from error

    payment.authorization_url = data.get("authorization_url", "")
    payment.save(update_fields=["authorization_url", "updated_at"])
    return payment


@transaction.atomic
def grant_free_period(user, plan, promo, discount):
    """A code that covers the whole price: the plan starts at once, with
    a paid Payment of zero recorded so the history and receipt still read
    the same way."""
    subscription = subscription_for(user)
    now = timezone.now()
    start = subscription.next_period_start(now)
    end = start + timedelta(days=plan.duration_days)

    payment = Payment.objects.create(
        reference=new_reference(),
        subscription=subscription,
        plan=plan,
        payer=user,
        account_name=str(subscription),
        email=user.email,
        plan_name=(f"{plan.name} · {plan.band_label}" if plan.band_label else plan.name)[:80],
        duration_days=plan.duration_days,
        amount=0,
        discount=discount,
        promo_code=promo.code,
        status=Payment.STATUS_SUCCESS,
        channel="promo",
        gateway_response=f"Paid in full by promo code {promo.code}",
        paid_at=now,
        period_start=start,
        period_end=end,
    )
    PromoRedemption.objects.create(promo=promo, user=user, payment=payment, amount_off=discount)

    subscription.paid_until = end
    if subscription.trial_ends_at and subscription.trial_ends_at > now:
        subscription.trial_ends_at = now
    subscription.plan = plan
    subscription.save(update_fields=["paid_until", "trial_ends_at", "plan", "updated_at"])
    logger.info("Promo code %s gave %s %s until %s", promo.code, subscription, plan, end)
    return payment


def grant_plan(user, plan, granted_by=None):
    """A plan given in the control room, without payment: its days start at
    once (after any paid time still to run), recorded as a paid Payment of
    zero so the history and receipt read the same way. For a teacher or
    school admin the plan covers their school."""
    subscription = subscription_for(user)
    if subscription is None:
        raise CheckoutError("This account doesn't pay for access, so it can't be given a plan.")
    return _grant(subscription, plan, payer=user, email=user.email, granted_by=granted_by)


def grant_school_plan(school, plan, granted_by=None):
    """The same, given to a school from its own page in the control room."""
    subscription, _made = Subscription.objects.get_or_create(school=school)
    return _grant(subscription, plan, payer=None, email=school.email, granted_by=granted_by)


@transaction.atomic
def _grant(subscription, plan, payer, email, granted_by):
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
    now = timezone.now()
    start = subscription.next_period_start(now)
    end = start + timedelta(days=plan.duration_days)
    by = f" by {granted_by.email}" if granted_by is not None else ""
    payment = Payment.objects.create(
        reference=new_reference(),
        subscription=subscription,
        plan=plan,
        payer=payer,
        account_name=str(subscription),
        email=email,
        plan_name=(f"{plan.name} · {plan.band_label}" if plan.band_label else plan.name)[:80],
        duration_days=plan.duration_days,
        amount=0,
        status=Payment.STATUS_SUCCESS,
        channel="control room",
        gateway_response=f"Given in the control room{by}"[:255],
        paid_at=now,
        period_start=start,
        period_end=end,
    )
    subscription.paid_until = end
    if subscription.trial_ends_at and subscription.trial_ends_at > now:
        subscription.trial_ends_at = now
    subscription.plan = plan
    subscription.save(update_fields=["paid_until", "trial_ends_at", "plan", "updated_at"])
    logger.info("Control room gave %s %s until %s%s", subscription, plan, end, by)
    return payment


def begin_access(request, user, start, plan, promo_code=""):
    """Straight after registering. The free trial is already running (see
    access.subscription_for), so "Pay now" can never leave someone with no
    access: they go to Paystack, and if the payment doesn't go through the
    trial simply carries on. Returns the address to go to next."""
    from django.contrib import messages
    from django.urls import reverse

    from .access import subscription_for
    from .models import BillingSettings

    subscription_for(user)                       # starts the trial
    days = BillingSettings.load().trial_days
    promo, refusal = find_promo(promo_code, user, plan)
    if refusal:
        messages.warning(request, refusal)
    home = "schools:dashboard" if user.role == user.Role.SCHOOL_ADMIN else "accounts:dashboard"
    if start == "pay" and plan is not None:
        try:
            payment = start_checkout(
                user, plan, promo=promo,
                callback_url=request.build_absolute_uri(reverse("billing:callback")),
                cancel_url=request.build_absolute_uri(reverse("billing:callback") + "?cancelled=1"),
            )
        except CheckoutError as error:
            messages.error(
                request,
                f"We couldn't open the payment page ({error}), so your {days}-day free trial has started instead. "
                "You can pay any time from Plans & billing.",
            )
            return reverse(home)
        if payment.is_paid:
            messages.success(
                request,
                f"Promo code {payment.promo_code} covered the whole price — your {payment.plan_name} plan is on.",
            )
            return reverse(home)
        return payment.authorization_url

    if promo is not None:
        messages.info(
            request,
            f"Your {days}-day free trial has started. Promo code {promo.code} ({promo.discount_label}) "
            "is still yours to use when you pay from Plans & billing.",
        )
        return reverse(home)
    if days:
        messages.success(request, f"Your {days}-day free trial has started. Enjoy exploring!")
    return reverse(home)


def confirm(reference):
    """Ask Paystack about a payment and act on the answer. Returns the
    Payment (or None for a reference we never issued)."""
    if not Payment.objects.filter(reference=reference).exists():
        return None
    data = paystack.verify(reference)
    return fulfil(reference, data)


def _paid_at(data):
    for key in ("paid_at", "paidAt", "transaction_date"):
        moment = parse_datetime(str(data.get(key) or ""))
        if moment:
            return moment
    return timezone.now()


@transaction.atomic
def fulfil(reference, data):
    """Apply Paystack's verified record `data` to our payment, once."""
    payment = Payment.objects.select_for_update().get(reference=reference)
    if payment.status == Payment.STATUS_SUCCESS:
        return payment                                   # already done — nothing to add

    status = str(data.get("status") or "")
    payment.raw = data
    payment.channel = str(data.get("channel") or "")[:30]
    payment.gateway_response = str(data.get("gateway_response") or "")[:255]

    if status != "success":
        if status in ("failed", "reversed"):
            payment.status = Payment.STATUS_FAILED
        elif status == "abandoned":
            payment.status = Payment.STATUS_ABANDONED
        payment.save()
        if payment.status in (Payment.STATUS_FAILED, Payment.STATUS_ABANDONED):
            PromoRedemption.objects.filter(payment=payment).delete()
        return payment

    # Paid — but for exactly what we asked? A tampered or mismatched
    # amount never buys access.
    if int(data.get("amount") or 0) != payment.amount or str(data.get("currency") or "").upper() != payment.currency:
        logger.error(
            "Paystack payment %s doesn't match: expected %s %s, got %s %s",
            reference, payment.amount, payment.currency, data.get("amount"), data.get("currency"),
        )
        payment.status = Payment.STATUS_FAILED
        payment.gateway_response = "Amount didn't match the plan. Contact support."
        payment.save()
        PromoRedemption.objects.filter(payment=payment).delete()
        return payment

    if payment.subscription_id is None:
        logger.error("Paystack payment %s succeeded but its account no longer exists.", reference)
        payment.status = Payment.STATUS_SUCCESS
        payment.paid_at = _paid_at(data)
        payment.save()
        return payment

    subscription = Subscription.objects.select_for_update().get(pk=payment.subscription_id)
    now = timezone.now()
    start = subscription.next_period_start(now)
    end = start + timedelta(days=payment.duration_days)
    subscription.paid_until = end
    # It's the trial or a paid plan, never both: paying ends a running trial.
    if subscription.trial_ends_at and subscription.trial_ends_at > now:
        subscription.trial_ends_at = now
    if payment.plan_id:
        subscription.plan_id = payment.plan_id
    subscription.save(update_fields=["paid_until", "trial_ends_at", "plan", "updated_at"])

    payment.status = Payment.STATUS_SUCCESS
    payment.paid_at = _paid_at(data)
    payment.period_start = start
    payment.period_end = end
    payment.save()
    logger.info("Payment %s: %s paid until %s", reference, subscription, end)
    return payment
