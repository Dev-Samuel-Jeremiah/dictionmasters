import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import paystack
from .access import (
    is_exempt, plans_for, price_table, status_for, student_count, student_plans_for_count, subscription_for, teacher_count,
)
from .models import BillingSettings, Payment, Plan
from .services import CheckoutError, confirm, find_promo, fulfil, start_checkout
from .templatetags.billing import naira

logger = logging.getLogger(__name__)

NEXT_KEY = "billing_next"


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return ""


def _active_plans(audience):
    return list(Plan.objects.filter(is_active=True, audience=audience))


def pricing(request):
    """The public price lists: schools by teachers, students per child, adults."""
    return render(request, "billing/pricing.html", {
        "school_table": price_table(_active_plans(Plan.AUDIENCE_SCHOOL)),
        "student_table": price_table(_active_plans(Plan.AUDIENCE_STUDENT)),
        "adult_plans": _active_plans(Plan.AUDIENCE_INDIVIDUAL),
        "settings": BillingSettings.load(),
    })


@login_required
def account(request):
    """Your access, the plans you can buy, and what you've paid."""
    user = request.user
    next_url = _safe_next(request, request.GET.get("next", ""))
    if next_url:
        request.session[NEXT_KEY] = next_url

    status = status_for(user) or {}
    subscription = status.get("subscription")
    school = user.school if user.school_id else None
    offered = plans_for(user) if (status.get("can_pay") or is_exempt(user)) else []

    held, refusal = _promo_in_hand(request)
    if refusal:
        messages.info(request, refusal)
    context = {
        "status": status,
        "promo": held,
        "payments": subscription.payments.all()[:30] if subscription else [],
        "next_url": next_url or request.session.get(NEXT_KEY, ""),
        "configured": paystack.is_configured(),
        "live": paystack.is_live(),
        "cards": [], "table": None,
    }
    if user.role == user.Role.SCHOOL_ADMIN and school:
        context["teachers"] = teacher_count(school)
        context["table"] = price_table([plan for plan, _ok, _why in offered],
                                       {plan.pk: (ok, why) for plan, ok, why in offered})
    else:
        context["cards"] = [plan for plan, ok, _why in offered if ok]
        for plan in context["cards"]:
            # What the code in hand makes this plan cost, for its card.
            plan.promo_price = (Decimal(held.price_after(plan.amount_kobo)) / 100
                                if held is not None and held.problem_for(user, plan) is None else None)
    if user.role == user.Role.STUDENT and school:
        context["children"] = student_count(school)
    return render(request, "billing/account.html", context)


@require_GET
def student_prices(request):
    """The per-child prices for one school, for the student sign-up form."""
    from apps.schools.models import School

    school = School.objects.filter(code=request.GET.get("code", "").strip().upper()).first()
    if school is None:
        return JsonResponse({"found": False})
    plans = student_plans_for_count(student_count(school) + 1)

    return JsonResponse({
        "found": True,
        "school": school.name,
        "options": [{"period": plan.name, "price": naira(plan.price), "text": plan.period_text} for plan in plans],
    })


PROMO_KEY = "promo-code"


def _promo_in_hand(request, plan=None):
    """The promo code this person has entered, if it still works. One that
    has since expired or been used up is quietly put down."""
    found, refusal = find_promo(request.session.get(PROMO_KEY, ""), request.user, plan)
    if refusal:
        request.session.pop(PROMO_KEY, None)
        return None, refusal
    return found, None


@login_required
@require_POST
def promo(request):
    """Enter a promo code, or take it off again."""
    if request.POST.get("remove"):
        request.session.pop(PROMO_KEY, None)
        messages.info(request, "Promo code removed.")
        return redirect("billing:account")

    found, refusal = find_promo(request.POST.get("code", ""), request.user)
    if refusal:
        messages.error(request, refusal)
    elif found is None:
        messages.error(request, "Enter the code you were given.")
    else:
        request.session[PROMO_KEY] = found.code
        messages.success(request, f"Promo code {found.code} applied — {found.discount_label} on your next payment.")
    return redirect("billing:account")


@login_required
@require_POST
def checkout(request, slug):
    plan = get_object_or_404(Plan, slug=slug)
    held, refusal = _promo_in_hand(request, plan)
    if refusal:
        messages.warning(request, refusal)
    try:
        payment = start_checkout(
            request.user, plan, promo=held,
            callback_url=request.build_absolute_uri(reverse("billing:callback")),
            cancel_url=request.build_absolute_uri(reverse("billing:account")),
        )
    except CheckoutError as error:
        messages.error(request, str(error))
        return redirect("billing:account")
    request.session.pop(PROMO_KEY, None)
    if payment.is_paid:
        messages.success(request, f"Promo code {payment.promo_code} covered the whole price. You're all set.")
        return redirect("billing:receipt", reference=payment.reference)
    return redirect(payment.authorization_url)


def _not_paid_message(user, opening):
    """What to say when a payment didn't complete: the trial, which started
    at registration, is still what they're on."""
    subscription = subscription_for(user)
    if subscription and subscription.state() == subscription.STATE_TRIAL:
        days = subscription.days_left()
        return f"{opening} Your free trial is active with {days} day{'s' if days != 1 else ''} left — you can pay any time."
    return f"{opening} You can try again below."


@login_required
@require_GET
def callback(request):
    """Where Paystack sends the customer back. The payment is checked with
    Paystack before anything is granted."""
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    home = "schools:dashboard" if request.user.role == request.user.Role.SCHOOL_ADMIN else "accounts:dashboard"
    if not reference and request.GET.get("cancelled"):
        # Paystack's "Cancel payment" straight after registering.
        messages.info(request, _not_paid_message(request.user, "You cancelled the payment, so you haven't been charged."))
        return redirect(home)
    payment = Payment.objects.filter(reference=reference).first()
    if payment is None:
        raise Http404("We don't recognise that payment.")

    try:
        payment = confirm(reference)
    except paystack.PaystackError:
        messages.info(
            request,
            "We couldn't confirm your payment with Paystack just now. If you were charged, your plan "
            "will switch on within a few minutes — there's no need to pay again.",
        )
        return redirect("billing:account")

    if payment.is_paid:
        messages.success(request, f"Payment received — thank you! Your {payment.plan_name} plan is active.")
        return redirect("billing:receipt", reference=payment.reference)
    if payment.status == Payment.STATUS_PENDING:
        messages.info(request, _not_paid_message(request.user, "Your payment is still being processed."))
    else:
        messages.error(request, _not_paid_message(request.user, "That payment didn't go through, so you haven't been charged."))
    return redirect("billing:account")


@login_required
def receipt(request, reference):
    payment = get_object_or_404(Payment.objects.select_related("subscription__school", "subscription__user"), reference=reference)
    user = request.user
    subscription = payment.subscription
    own = payment.payer_id == user.pk or (
        subscription is not None and (
            subscription.user_id == user.pk
            or (subscription.school_id and user.school_id == subscription.school_id and user.role == user.Role.SCHOOL_ADMIN)
        )
    )
    if not (own or is_exempt(user)):
        raise Http404("No such receipt.")
    return render(request, "billing/receipt.html", {
        "payment": payment,
        "settings": BillingSettings.load(),
        "next_url": request.session.pop(NEXT_KEY, "") if payment.is_paid else "",
    })


@csrf_exempt
@require_POST
def webhook(request):
    """Paystack telling us about a payment, whether or not the customer
    made it back to the site."""
    if not paystack.signature_is_valid(request.body, request.headers.get("x-paystack-signature", "")):
        return HttpResponseBadRequest("Bad signature.")
    try:
        event = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("Bad body.")

    if event.get("event") == "charge.success":
        reference = str((event.get("data") or {}).get("reference") or "")
        if Payment.objects.filter(reference=reference).exists():
            try:
                # Checked with Paystack again rather than taken from the
                # message, so a replayed or edited event can't grant access.
                fulfil(reference, paystack.verify(reference))
            except paystack.PaystackError:
                # A non-200 makes Paystack send it again later.
                return HttpResponse(status=503)
    return HttpResponse(status=200)
