"""
The Diction Masters price sheets, loaded as plans (all editable in the
control room afterwards):

- Schools, by number of teachers, termly and yearly.
- Students at home, per child, by how many children the school has
  enrolled, termly and yearly.
- Adults (non-students): weekly, monthly, quarterly, yearly.

The earlier ₦100 placeholder plans are removed if nobody has paid for one.
Students used to be covered by their school; now they pay for themselves,
so each existing student gets the same 7-day trial a new one can choose.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

TERM_DAYS = 122   # a third of a year
YEAR_DAYS = 365

# (up to N teachers, termly, yearly). Each tier starts one above the last.
SCHOOL_TIERS = [
    (5, 48000, 115200), (10, 72000, 172800), (20, 96000, 230400), (25, 120000, 288000),
    (30, 144000, 345600), (35, 168000, 403200), (40, 192000, 460800), (45, 216000, 518400),
    (50, 240000, 576000),
]

# (from, up to — None for no limit, termly per child, yearly per child)
STUDENT_BANDS = [
    (1, 50, 2000, 4800), (51, 100, 1800, 4320), (101, 200, 1600, 3840), (201, 300, 1400, 3360),
    (301, 400, 1200, 2880), (401, 500, 1000, 2400), (501, None, 800, 1920),
]

ADULT_PLANS = [
    ("Weekly", 7, 1800, False), ("Monthly", 30, 2500, True), ("Quarterly", 91, 6500, False), ("Yearly", 365, 20000, False),
]


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Payment = apps.get_model("billing", "Payment")
    Subscription = apps.get_model("billing", "Subscription")
    User = apps.get_model("accounts", "User")

    paid_for = set(Payment.objects.exclude(plan=None).values_list("plan_id", flat=True))
    Plan.objects.filter(price=Decimal("100"), is_active=False).exclude(pk__in=paid_for).delete()

    def add(**fields):
        if not Plan.objects.filter(slug=fields["slug"]).exists():
            Plan.objects.create(**fields)

    for name, days, price, featured in ADULT_PLANS:
        add(slug=f"adult-{name.lower()}", audience="individual", name=name, duration_days=days,
            price=Decimal(price), is_featured=featured,
            features="Every learning tool\nEchoSpell, Quick Words and Diction Clash\nYour progress saved")

    low = 1
    for top, termly, yearly in SCHOOL_TIERS:
        for name, days, price in (("Termly", TERM_DAYS, termly), ("Yearly", YEAR_DAYS, yearly)):
            add(slug=f"school-{name.lower()}-{low}-{top}", audience="school", name=name, duration_days=days,
                price=Decimal(price), min_units=low, max_units=top)
        low = top + 1

    for low, top, termly, yearly in STUDENT_BANDS:
        for name, days, price in (("Termly", TERM_DAYS, termly), ("Yearly", YEAR_DAYS, yearly)):
            add(slug=f"student-{name.lower()}-{low}-{top or 'plus'}", audience="student", name=name,
                duration_days=days, price=Decimal(price), min_units=low, max_units=top)

    covered = set(Subscription.objects.exclude(user=None).values_list("user_id", flat=True))
    ends = timezone.now() + timedelta(days=7)
    Subscription.objects.bulk_create([
        Subscription(user_id=pk, trial_ends_at=ends)
        for pk in User.objects.filter(role="student", is_staff=False).values_list("pk", flat=True)
        if pk not in covered
    ])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_price_sheets")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
