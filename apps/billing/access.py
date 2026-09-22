"""
Who is covered by which subscription, what they may buy, and whether they
may use the tools.

    adult (individual)  → their own subscription, adult plans
    student             → their own subscription, per-child plans for the
                          band their school's enrolment falls in
    school admin        → the school's subscription, teacher tiers
    teacher             → the school's subscription (the admin pays)
    staff               → always allowed, never billed

Every account is always on its free trial or a paid plan. The trial starts
the first time the account is seen — at registration — and each account
only ever has it once. Staff are never billed.
"""

from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from .models import BillingSettings, Plan, Subscription

# The learning itself. Everything else — the dashboard, account pages,
# billing, the school admin's page — stays open whatever the state.
GATED_PREFIXES = (
    "/learning-tools/",
    "/book/",
    "/tricks/",
    "/reference-library/",
    "/daily-practice/",
    "/learning-modules/",
    "/reading-club/",
    "/echospell/",
    "/quick-words/",
    "/tutor/",
    "/assessments/",
    "/clash/",
)


def is_exempt(user):
    return bool(user.is_staff or user.is_superuser)


def pays_for_self(user):
    return user.role in (user.Role.INDIVIDUAL, user.Role.STUDENT)


def can_pay(user):
    """Adults and students pay for themselves; a school admin pays for the school."""
    return pays_for_self(user) or user.role == user.Role.SCHOOL_ADMIN


def audience_for(user):
    if user.role == user.Role.STUDENT:
        return Plan.AUDIENCE_STUDENT
    if user.role == user.Role.INDIVIDUAL:
        return Plan.AUDIENCE_INDIVIDUAL
    return Plan.AUDIENCE_SCHOOL


def _owner(user):
    if pays_for_self(user):
        return {"user": user}
    if getattr(user, "school_id", None):
        return {"school": user.school}
    return None


def subscription_for(user):
    """The subscription covering `user`, made if it doesn't exist yet (with
    no trial or paid time). None for staff, and for a teacher or school
    admin whose account has no school."""
    if not getattr(user, "is_authenticated", False) or is_exempt(user):
        return None
    owner = _owner(user)
    if owner is None:
        return None
    found = Subscription.objects.select_related("plan").filter(**owner).first()
    if found is None:
        try:
            found = Subscription.objects.create(**owner)
        except IntegrityError:       # two requests at once: the other one made it
            found = Subscription.objects.select_related("plan").get(**owner)
    # Never on neither: an account that hasn't had its trial and hasn't
    # paid gets the trial now, and it starts counting straight away.
    if found.trial_ends_at is None and found.paid_until is None:
        _begin_trial(found)
    return found


def _begin_trial(subscription):
    settings_ = BillingSettings.load()
    if not trial_available(subscription, settings_):
        return False
    ends = timezone.now() + timedelta(days=settings_.trial_days)
    started = Subscription.objects.filter(pk=subscription.pk, trial_ends_at__isnull=True).update(
        trial_ends_at=ends, updated_at=timezone.now(),
    )
    if started:
        subscription.trial_ends_at = ends
    return bool(started)


def trial_available(subscription, settings_=None):
    """The free trial is for accounts that have never had one and never
    paid: once anything has been bought, it's gone for good."""
    settings_ = settings_ or BillingSettings.load()
    if not (subscription and settings_.trial_days and subscription.trial_ends_at is None):
        return False
    if subscription.paid_until is not None:
        return False
    from .models import Payment

    return not subscription.payments.filter(status=Payment.STATUS_SUCCESS).exists()


def start_trial(user):
    """Make sure whoever covers `user` has had their free trial. It starts by
    itself the first time the account is seen; this is for being explicit.
    Returns True if the account is on its trial now."""
    if not can_pay(user):
        return False
    subscription = subscription_for(user)
    return bool(subscription and subscription.state() == Subscription.STATE_TRIAL)


def has_access(user):
    if not getattr(user, "is_authenticated", False) or is_exempt(user):
        return True
    if not BillingSettings.load().paywall_enabled:
        return True
    subscription = subscription_for(user)
    # A teacher whose account isn't linked to a school has nothing to be
    # billed against; don't lock them out over that.
    return True if subscription is None else subscription.has_access()


# ---------------------------------------------------------------------------
# Counting, and the plans someone can buy
# ---------------------------------------------------------------------------

def teacher_count(school):
    return school.members.filter(role="teacher").count()


def student_count(school):
    return school.members.filter(role="student").count()


def student_plans_for_count(count):
    """The per-child plans for a school with `count` enrolled children."""
    return [plan for plan in Plan.objects.filter(is_active=True, audience=Plan.AUDIENCE_STUDENT) if plan.fits(count)]


def plans_for(user):
    """[(plan, can_buy, reason)] for everything shown to `user` on the billing page."""
    audience = audience_for(user)
    if audience == Plan.AUDIENCE_STUDENT:
        if not user.school_id:
            return []
        return [(plan, True, "") for plan in student_plans_for_count(max(student_count(user.school), 1))]

    plans = Plan.objects.filter(is_active=True, audience=audience)
    if audience == Plan.AUDIENCE_SCHOOL:
        teachers = teacher_count(user.school) if user.school_id else 0
        return [
            (plan, plan.max_units is None or plan.max_units >= teachers,
             "" if plan.max_units is None or plan.max_units >= teachers
             else f"You already have {teachers} teachers")
            for plan in plans
        ]
    return [(plan, True, "") for plan in plans]


def purchasable(user, plan):
    """None if `user` may buy `plan`, otherwise the reason they can't."""
    if not can_pay(user):
        return "Your school pays for your access. Please ask your school admin."
    if not plan.is_active:
        return "That plan isn't available any more. Please choose another."
    if plan.audience != audience_for(user):
        return "That plan isn't for your kind of account."
    for offered, can_buy, reason in plans_for(user):
        if offered.pk == plan.pk:
            return None if can_buy else f"{reason}, so please choose a bigger plan."
    if plan.audience == Plan.AUDIENCE_STUDENT:
        return "Prices have changed for your school's size. Please choose again."
    return "That plan isn't available to you."


# ---------------------------------------------------------------------------
# For templates
# ---------------------------------------------------------------------------

def status_for(user):
    """Everything the banner and billing pages need to describe someone's access."""
    if not getattr(user, "is_authenticated", False):
        return None
    settings_ = BillingSettings.load()
    if is_exempt(user):
        return {"exempt": True, "paywall": settings_.paywall_enabled}
    subscription = subscription_for(user)
    if subscription is None:
        return None
    now = timezone.now()
    state = subscription.state(now)
    days = subscription.days_left(now)
    return {
        "exempt": False,
        "paywall": settings_.paywall_enabled,
        "subscription": subscription,
        "state": state,
        "days_left": days,
        "access_until": subscription.access_until,
        "has_access": subscription.has_access(now) or not settings_.paywall_enabled,
        "can_pay": can_pay(user),
        "trial_available": can_pay(user) and trial_available(subscription, settings_),
        "never_started": subscription.trial_ends_at is None and subscription.paid_until is None,
        "school": subscription.school or (user.school if user.role == user.Role.STUDENT else None),
        "renew_soon": state != Subscription.STATE_EXPIRED and days <= settings_.reminder_days,
        "settings": settings_,
    }


def price_table(plans, can_buy=None):
    """Plans laid out like the price sheets: a row per tier or band, a
    column per period. `can_buy` maps plan pk → (bool, reason)."""
    periods = []
    for plan in sorted(plans, key=lambda p: (p.duration_days, p.name)):
        if plan.name not in periods:
            periods.append(plan.name)
    rows = {}
    for plan in plans:
        key = (plan.min_units or 0, plan.max_units if plan.max_units is not None else 10**9)
        row = rows.setdefault(key, {"label": plan.band_label, "cells": {}, "can_buy": True, "reason": ""})
        row["cells"][plan.name] = plan
        if can_buy and plan.pk in can_buy:
            ok, reason = can_buy[plan.pk]
            row["can_buy"] = row["can_buy"] and ok
            row["reason"] = row["reason"] or reason
    ordered = [rows[key] for key in sorted(rows)]
    for row in ordered:
        row["cells"] = [(name, row["cells"].get(name)) for name in periods]
    return {"periods": periods, "rows": ordered}
