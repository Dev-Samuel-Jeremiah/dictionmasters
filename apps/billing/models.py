"""
Paying for Diction Masters.

Who pays
--------
Three kinds of customer, each with its own price list:

    adults (non-students)  pay for themselves: weekly, monthly, quarterly, yearly
    schools                pay by how many teachers they have (a tier), termly or
                           yearly; that covers the school admin and its teachers
    students               pay for themselves when they register with their
                           school's code; the price per child depends on how many
                           children that school has enrolled (a band)

Staff never pay.

How it works
------------
Every paying account (an adult, a student, or a school) has one
Subscription, and it is always either on its free trial or paid for —
never neither. The trial starts the moment the account exists, so someone
who chooses "Pay now" and doesn't finish paying is still covered. A
successful payment ends the trial and starts the plan at once; renewing a
paid plan early adds the new days after the time still left.

Payment is once per period through Paystack (card, bank transfer, USSD),
never an automatic charge. Every attempt is a Payment row, and a Payment
only ever grants access once, however many times Paystack reports it.

Everything a customer sees — plan names, prices, lengths, what's
included, the trial length — is set in the control room.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify


class BillingSettings(models.Model):
    """The site-wide rules. Only ever one row."""

    paywall_enabled = models.BooleanField(
        default=True,
        help_text="Untick to let everyone use every tool for free, e.g. while plans are being set up.",
    )
    trial_days = models.PositiveIntegerField(
        default=7, help_text="Days of free access for a new learner or school. 0 turns the trial off.",
    )
    reminder_days = models.PositiveIntegerField(
        default=5,
        help_text="Renewal is offered this many days before access ends. People can still renew earlier; the days add on.",
    )
    support_email = models.EmailField(blank=True, help_text="Shown on receipts and the plans page for billing questions.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "billing settings"
        verbose_name_plural = "billing settings"

    def __str__(self):
        return "Billing settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)


class Plan(models.Model):
    """One price: a period (e.g. Termly) for one kind of customer, and for
    schools and students one size band (e.g. up to 5 teachers, or 51–100
    children). The price lists on the site are built from these rows."""

    AUDIENCE_INDIVIDUAL = "individual"
    AUDIENCE_SCHOOL = "school"
    AUDIENCE_STUDENT = "student"
    AUDIENCE_CHOICES = [
        (AUDIENCE_INDIVIDUAL, "Adults (non-students)"),
        (AUDIENCE_SCHOOL, "Schools, by number of teachers"),
        (AUDIENCE_STUDENT, "Students, per child"),
    ]
    UNIT_NAMES = {AUDIENCE_SCHOOL: "teachers", AUDIENCE_STUDENT: "children"}

    name = models.CharField(max_length=80, help_text='The period, e.g. "Weekly", "Termly", "Yearly". Plans with the same name share a column in the price tables.')
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default=AUDIENCE_INDIVIDUAL)
    description = models.CharField(max_length=200, blank=True, help_text="One line under the price.")
    features = models.TextField(blank=True, help_text="What's included, one per line.")
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("100"))],
        help_text="In naira, e.g. 48000. For students this is the price per child. Paystack's smallest charge is ₦100.",
    )
    duration_days = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(1)],
        help_text="Days of access it buys: 7 a week, 30 a month, 91 a quarter, 122 a term, 365 a year.",
    )
    period_label = models.CharField(
        max_length=30, blank=True, help_text='Shown after the price, e.g. "per term". Worked out from the name if left blank.',
    )
    min_units = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="from",
        help_text="Schools: fewest teachers in this tier. Students: fewest enrolled children in this band. Blank for adults.",
    )
    max_units = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="up to",
        help_text="Schools: most teachers this tier allows. Students: most enrolled children in this band — blank for no upper limit (e.g. 500+).",
    )
    is_featured = models.BooleanField(default=False, help_text='Highlighted as "Most popular".')
    is_active = models.BooleanField(default=True, help_text="Only active plans are shown and can be bought.")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["audience", "min_units", "max_units", "duration_days", "order", "price"]

    def __str__(self):
        band = f" · {self.band_label}" if self.band_label else ""
        return f"{self.name}{band} ({self.get_audience_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.audience == self.AUDIENCE_SCHOOL and not self.max_units:
            raise ValidationError({"max_units": "A school tier needs the most teachers it allows."})
        if self.min_units and self.max_units and self.min_units > self.max_units:
            raise ValidationError({"max_units": "“Up to” can't be smaller than “from”."})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.audience}-{self.name}-{self.band_label}") or "plan"
            slug, n = base, 1
            while Plan.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def amount_kobo(self):
        return int((self.price * 100).quantize(Decimal("1")))

    @property
    def unit_name(self):
        return self.UNIT_NAMES.get(self.audience, "")

    @property
    def band_label(self):
        """ "1–5 teachers", "51–100 children", "500+ children", or "" for adults."""
        if self.audience == self.AUDIENCE_INDIVIDUAL or (self.min_units is None and self.max_units is None):
            return ""
        low = self.min_units or 1
        if self.max_units is None:
            return f"{max(low - 1, 1)}+ {self.unit_name}" if low > 1 else f"Any number of {self.unit_name}"
        return f"{low}–{self.max_units} {self.unit_name}"

    def fits(self, count):
        """Whether `count` teachers or children fall inside this tier or band."""
        return (self.min_units is None or count >= self.min_units) and (self.max_units is None or count <= self.max_units)

    @property
    def feature_list(self):
        return [line.strip(" -•\t") for line in self.features.splitlines() if line.strip(" -•\t")]

    @property
    def period_text(self):
        if self.period_label:
            return self.period_label
        known = {"weekly": "per week", "monthly": "per month", "quarterly": "per quarter",
                 "termly": "per term", "yearly": "per year", "annually": "per year"}
        if self.name.strip().lower() in known:
            text = known[self.name.strip().lower()]
        else:
            text = f"for {self.duration_days} days"
        return text


class Subscription(models.Model):
    """One learner's or one school's access. Exactly one of `user` and
    `school` is set."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="subscription",
    )
    school = models.OneToOneField(
        "schools.School", on_delete=models.CASCADE, null=True, blank=True, related_name="subscription",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions",
        help_text="The plan last paid for.",
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    paid_until = models.DateTimeField(null=True, blank=True, help_text="Paid access runs until this moment.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(user__isnull=False, school__isnull=True) | Q(user__isnull=True, school__isnull=False)),
                name="billing_subscription_one_owner",
            ),
        ]

    def __str__(self):
        return self.school.name if self.school_id else (self.user.email if self.user_id else "Subscription")

    STATE_TRIAL = "trial"
    STATE_ACTIVE = "active"
    STATE_EXPIRED = "expired"

    @property
    def access_until(self):
        ends = [moment for moment in (self.trial_ends_at, self.paid_until) if moment]
        return max(ends) if ends else None

    def has_access(self, now=None):
        until = self.access_until
        return bool(until and (now or timezone.now()) < until)

    def state(self, now=None):
        now = now or timezone.now()
        if self.paid_until and now < self.paid_until:
            return self.STATE_ACTIVE
        if self.trial_ends_at and now < self.trial_ends_at:
            return self.STATE_TRIAL
        return self.STATE_EXPIRED

    def days_left(self, now=None):
        """Whole days of access left, counting today; 0 once it has ended."""
        now = now or timezone.now()
        until = self.access_until
        if not until or until <= now:
            return 0
        return max(1, (until - now).days + (1 if (until - now).seconds else 0))

    def next_period_start(self, now=None):
        """Where newly bought days begin: now, or after paid time still to
        run. A free trial doesn't push it back — paying ends the trial."""
        now = now or timezone.now()
        return max(now, self.paid_until) if self.paid_until else now

    @property
    def audience(self):
        return Plan.AUDIENCE_SCHOOL if self.school_id else Plan.AUDIENCE_INDIVIDUAL


class Payment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_ABANDONED, "Not completed"),
    ]

    reference = models.CharField(max_length=64, unique=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, related_name="payments")
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="payments")

    # Copied at checkout, so a receipt never changes when a plan is edited
    # or an account is deleted.
    account_name = models.CharField(max_length=255)
    email = models.EmailField()
    plan_name = models.CharField(max_length=80)
    duration_days = models.PositiveIntegerField()
    amount = models.PositiveBigIntegerField(help_text="In kobo.")
    discount = models.PositiveBigIntegerField(default=0, help_text="Taken off by a promo code, in kobo.")
    promo_code = models.CharField(max_length=20, blank=True, help_text="The code used, as it was typed.")
    currency = models.CharField(max_length=3, default="NGN")

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    channel = models.CharField(max_length=30, blank=True)
    gateway_response = models.CharField(max_length=255, blank=True)
    authorization_url = models.URLField(max_length=500, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True, help_text="Paystack's last word on this payment.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference

    @property
    def amount_naira(self):
        return Decimal(self.amount) / 100

    @property
    def amount_display(self):
        from .templatetags.billing import naira

        return naira(self.amount_naira)

    @property
    def full_price_naira(self):
        return Decimal(self.amount + self.discount) / 100

    @property
    def discount_naira(self):
        return Decimal(self.discount) / 100

    CHANNEL_NAMES = {
        "card": "Card", "bank": "Bank account", "bank_transfer": "Bank transfer", "ussd": "USSD",
        "qr": "QR code", "mobile_money": "Mobile money", "apple_pay": "Apple Pay", "eft": "EFT",
    }

    @property
    def channel_display(self):
        return self.CHANNEL_NAMES.get(self.channel, self.channel.replace("_", " ").capitalize())

    @property
    def is_paid(self):
        return self.status == self.STATUS_SUCCESS

    @property
    def expires_soon(self):
        """A checkout link Paystack has probably closed, for display only."""
        return self.status == self.STATUS_PENDING and timezone.now() - self.created_at > timedelta(hours=1)


class PromoCode(models.Model):
    """A code like JDM201 that takes money off a plan at checkout.

    Each code carries its own limits: how many accounts may use it, when
    it stops working, which plans it applies to, and how much it takes
    off (a percentage, or a flat sum in naira). A code that takes the
    whole price off gives the plan free — the account is granted its
    period without going to Paystack at all.
    """

    PERCENT = "percent"
    AMOUNT = "amount"
    KIND_CHOICES = [(PERCENT, "Percentage off"), (AMOUNT, "Naira off")]

    code = models.CharField(
        max_length=20, unique=True, blank=True,
        help_text='What people type, e.g. "JDM201". Leave blank and one is made for you.',
    )
    note = models.CharField(
        max_length=150, blank=True, help_text="For your own records, e.g. “September school fair”. Never shown.",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=PERCENT)
    value = models.DecimalField(
        max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))],
        help_text="How much off: a percentage (e.g. 25 for 25% off), or an amount in naira.",
    )
    max_uses = models.PositiveIntegerField(
        default=0, help_text="How many accounts may use it. 0 means no limit.",
    )
    once_per_account = models.BooleanField(
        default=True, help_text="An account can use this code only once.",
    )
    starts_at = models.DateTimeField(null=True, blank=True, help_text="Leave blank to start straight away.")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Leave blank for no end date.")
    plans = models.ManyToManyField(
        Plan, blank=True, related_name="promo_codes",
        help_text="The plans it works on. Choose none for every plan.",
    )
    is_active = models.BooleanField(default=True, help_text="Turn off to stop it working at once.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "promo code"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper().replace(" ", "")
        if not self.code:
            self.code = self.make_code()
        super().save(*args, **kwargs)

    @staticmethod
    def make_code(prefix="JDM"):
        """A fresh code in the house style: JDM201, JDM874…"""
        import random

        for _ in range(200):
            code = f"{prefix}{random.randint(100, 999)}"
            if not PromoCode.objects.filter(code=code).exists():
                return code
        return f"{prefix}{uuid.uuid4().hex[:5].upper()}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.kind == self.PERCENT and self.value > 100:
            raise ValidationError({"value": "A percentage can't be more than 100."})
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValidationError({"expires_at": "The end date must come after the start date."})

    # ---------------------------------------------------------------- limits

    @property
    def used(self):
        return self.redemptions.count()

    @property
    def uses_left(self):
        """None when there is no limit."""
        return None if not self.max_uses else max(self.max_uses - self.used, 0)

    @property
    def has_started(self):
        return not self.starts_at or self.starts_at <= timezone.now()

    @property
    def has_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())

    @property
    def is_live(self):
        return self.is_active and self.has_started and not self.has_expired and self.uses_left != 0

    @property
    def state(self):
        if not self.is_active:
            return "Turned off"
        if not self.has_started:
            return "Not started"
        if self.has_expired:
            return "Expired"
        if self.uses_left == 0:
            return "All used"
        return "Live"

    @property
    def discount_label(self):
        if self.kind == self.PERCENT:
            return f"{self.value.normalize():f}% off".replace(".0%", "%")
        from .templatetags.billing import naira

        return f"{naira(self.value)} off"

    def problem_for(self, user, plan):
        """Why this code can't be used now, or None if it can."""
        if not self.is_active:
            return "That code isn't available."
        if not self.has_started:
            return "That code isn't active yet."
        if self.has_expired:
            return "That code has expired."
        if self.uses_left == 0:
            return "That code has been used up."
        if plan is not None and self.plans.exists() and not self.plans.filter(pk=plan.pk).exists():
            return "That code doesn't apply to this plan."
        if user is not None and self.once_per_account and self.redemptions.filter(user=user).exists():
            return "You've already used that code."
        return None

    # ---------------------------------------------------------------- money

    def discount_kobo(self, amount_kobo):
        """How much this code takes off, never more than the price."""
        if self.kind == self.PERCENT:
            off = (Decimal(amount_kobo) * self.value / 100).quantize(Decimal("1"))
        else:
            off = (self.value * 100).quantize(Decimal("1"))
        return min(int(off), int(amount_kobo))

    def price_after(self, amount_kobo):
        return int(amount_kobo) - self.discount_kobo(amount_kobo)


class PromoRedemption(models.Model):
    """One account's use of a code, kept so limits can be counted and a
    code's history read back."""

    promo = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promo_uses")
    payment = models.OneToOneField(
        "billing.Payment", on_delete=models.CASCADE, null=True, blank=True, related_name="redemption",
    )
    amount_off = models.PositiveBigIntegerField(default=0, help_text="In kobo.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "promo code use"
        verbose_name_plural = "promo code uses"

    def __str__(self):
        return f"{self.promo} — {self.user}"
