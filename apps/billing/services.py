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
from .models import Payment, Subscription

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """This person can't buy this plan right now; the message says why."""


def new_reference():
    return f"DM-{uuid.uuid4().hex[:20].upper()}"


def start_checkout(user, plan, *, callback_url, cancel_url):
    """Record a pending payment and ask Paystack for its checkout page.
    Returns the Payment, with authorization_url to send the customer to."""
    problem = purchasable(user, plan)
    if problem:
        raise CheckoutError(problem)
    subscription = subscription_for(user)
    if subscription is None:
        raise CheckoutError("There's no account to pay for yet.")

    payment = Payment.objects.create(
        reference=new_reference(),
        subscription=subscription,
        plan=plan,
        payer=user,
        account_name=str(subscription),
        email=user.email,
        plan_name=(f"{plan.name} · {plan.band_label}" if plan.band_label else plan.name)[:80],
        duration_days=plan.duration_days,
        amount=plan.amount_kobo,
    )
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


def begin_access(request, user, start, plan):
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
    home = "schools:dashboard" if user.role == user.Role.SCHOOL_ADMIN else "accounts:dashboard"
    if start == "pay" and plan is not None:
        try:
            payment = start_checkout(
                user, plan,
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
        return payment.authorization_url

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
