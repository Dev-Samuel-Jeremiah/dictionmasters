"""
Accounts that existed before billing get the same free trial as a new
sign-up, starting now, rather than finding their tools locked the day
payments go live. Draft plans are added switched off, for the prices to
be set in the control room before they're shown to anyone.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

TRIAL_DAYS = 7


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    School = apps.get_model("schools", "School")
    Subscription = apps.get_model("billing", "Subscription")
    Plan = apps.get_model("billing", "Plan")
    BillingSettings = apps.get_model("billing", "BillingSettings")

    BillingSettings.objects.get_or_create(pk=1, defaults={"trial_days": TRIAL_DAYS, "reminder_days": 3})
    ends = timezone.now() + timedelta(days=TRIAL_DAYS)

    covered_users = set(Subscription.objects.exclude(user=None).values_list("user_id", flat=True))
    Subscription.objects.bulk_create([
        Subscription(user_id=pk, trial_ends_at=ends)
        for pk in User.objects.filter(role="individual", is_staff=False).values_list("pk", flat=True)
        if pk not in covered_users
    ])
    covered_schools = set(Subscription.objects.exclude(school=None).values_list("school_id", flat=True))
    Subscription.objects.bulk_create([
        Subscription(school_id=pk, trial_ends_at=ends)
        for pk in School.objects.values_list("pk", flat=True)
        if pk not in covered_schools
    ])

    if not Plan.objects.exists():
        drafts = [
            ("individual", "Monthly", "individual-monthly", 30, 0, "Every learning tool for one learner."),
            ("individual", "Termly", "individual-termly", 91, 1, "A full school term of practice."),
            ("individual", "Yearly", "individual-yearly", 365, 2, "The best value for a whole year."),
            ("school", "Termly", "school-termly", 91, 0, "Every teacher and student in your school, for a term."),
            ("school", "Yearly", "school-yearly", 365, 1, "Your whole school, for the full academic year."),
        ]
        for audience, name, slug, days, order, description in drafts:
            Plan.objects.create(
                audience=audience, name=name, slug=slug, duration_days=days, order=order,
                description=description, price=Decimal("100"), is_active=False, is_featured=(order == 1),
            )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
        ("accounts", "0003_level"),
        ("schools", "0002_level"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
