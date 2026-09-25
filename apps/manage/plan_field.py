"""The "Give a plan" field on the control room's user and school forms: pick
a plan and the user (or, for a teacher or school admin, their school) or the
school gets its days at once, without paying. See billing.services."""

from django import forms
from django.utils import timezone

from apps.billing.access import audience_for, is_exempt, subscription_for
from apps.billing.models import Plan

FIELD = "grant_plan"


def _label(plan):
    band = f" · {plan.band_label}" if plan.band_label else ""
    return f"{plan.get_audience_display()} · {plan.name}{band} ({plan.duration_days} days)"


def _current_access(user):
    if user is None or not user.pk:
        return "Leave blank to start them on the free trial."
    if is_exempt(user):
        return "Staff accounts have full access and never need a plan."
    subscription = subscription_for(user)
    if subscription is None:
        return "This account has no school yet, so there is no access to give."
    whose = "Their school's access" if subscription.school_id else "Their access"
    state = subscription.state()
    until = subscription.access_until
    if state == subscription.STATE_ACTIVE:
        plan = f" on {subscription.plan.name}" if subscription.plan else ""
        now = f"{whose}: paid{plan} until {timezone.localtime(until):%d %b %Y}."
    elif state == subscription.STATE_TRIAL:
        now = f"{whose}: free trial until {timezone.localtime(until):%d %b %Y}."
    else:
        now = f"{whose}: ended."
    return f"{now} A plan chosen here is added on top. Leave blank to change nothing."


def _school_access(school):
    subscription = getattr(school, "subscription", None) if school is not None and school.pk else None
    if subscription is None or subscription.access_until is None:
        return "Choose a plan to give this school paid access now, or leave blank."
    until = f"{timezone.localtime(subscription.access_until):%d %b %Y}"
    state = subscription.state()
    if state == subscription.STATE_ACTIVE:
        plan = subscription.plan
        name = f" on {plan.name}{f' · {plan.band_label}' if plan and plan.band_label else ''}" if plan else ""
        now = f"Current plan: paid{name} until {until}."
    elif state == subscription.STATE_TRIAL:
        now = f"Free trial until {until}."
    else:
        now = "Access has ended."
    return f"{now} A plan chosen here is added on top. Leave blank to change nothing."


def add_plan_field(form, obj, kind="user"):
    plans = Plan.objects.filter(is_active=True)
    if kind == "school":
        plans = plans.filter(audience=Plan.AUDIENCE_SCHOOL)
    form.fields[FIELD] = forms.ModelChoiceField(
        queryset=plans.order_by("audience", "min_units", "duration_days", "order"),
        required=False,
        label="Give a plan",
        empty_label="No plan: keep the current access",
        help_text=_school_access(obj) if kind == "school" else _current_access(obj),
        widget=forms.Select(attrs={"class": "cr-input cr-select"}),
    )
    if kind == "school" and "max_teachers" in form.fields and obj is not None and obj.pk:
        plan = obj.paid_plan()
        if plan and plan.max_units:
            band = f" ({plan.name} · {plan.band_label})" if plan.band_label else f" ({plan.name})"
            form.fields["max_teachers"].help_text = (
                f"Their paid plan{band} allows up to {plan.max_units} teachers, and that limit already applies. "
                "Leave blank to use it, or set a lower number to limit them further."
            )
    form.fields[FIELD].label_from_instance = _label


def check_plan(form, user, kind="user"):
    """After form.is_valid(): make sure the chosen plan suits the account
    being saved. Adds an error to the field and returns False if not."""
    plan = form.cleaned_data.get(FIELD)
    if plan is None or kind == "school":
        return True
    from apps.accounts.models import User

    role = form.cleaned_data.get("role") or getattr(user, "role", "")
    school = form.cleaned_data["school"] if "school" in form.cleaned_data else getattr(user, "school", None)
    if form.cleaned_data.get("is_staff", getattr(user, "is_staff", False)) or getattr(user, "is_superuser", False):
        form.add_error(FIELD, "Staff accounts have full access and don't take a plan.")
        return False
    if role not in (User.Role.INDIVIDUAL, User.Role.STUDENT) and not school:
        form.add_error(FIELD, "Teachers and school admins share their school's plan: choose their school first.")
        return False
    wanted = audience_for(User(role=role))
    if plan.audience != wanted:
        names = dict(Plan.AUDIENCE_CHOICES)
        form.add_error(FIELD, f"This account needs a plan for “{names[wanted]}”, not “{names[plan.audience]}”.")
        return False
    return True
