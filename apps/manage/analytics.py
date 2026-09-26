"""The numbers behind the control room's Analytics page.

Everything is worked out for one period (a preset such as "last 30 days", or
a custom range) and compared with the period of the same length just before
it. Money is counted from successful Paystack payments only: a plan given in
the control room or a promo code that covers the whole price is a ₦0 payment,
so it is counted as a grant, never as revenue.
"""

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.apps import apps
from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Payment, Plan, PromoRedemption, Subscription
from apps.schools.models import School

PRESETS = OrderedDict([
    ("7d", ("Last 7 days", 7)),
    ("30d", ("Last 30 days", 30)),
    ("90d", ("Last 90 days", 90)),
    ("12m", ("Last 12 months", 365)),
    ("all", ("All time", None)),
])
DEFAULT_PRESET = "30d"
GRAINS = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}

ROLE_LABELS = OrderedDict([
    ("school_admin", "Schools"),
    ("individual", "Adults"),
    ("student", "Students"),
    ("teacher", "Teachers"),
])
AUDIENCE_LABELS = {
    Plan.AUDIENCE_SCHOOL: "Schools",
    Plan.AUDIENCE_INDIVIDUAL: "Adults",
    Plan.AUDIENCE_STUDENT: "Students",
}

# Learning activity: (key, label, "app.Model", date field). Models that
# don't exist in this install are skipped.
ACTIVITY_SOURCES = [
    ("echospell", "EchoSpell activities", "echospell.ActivityAttempt", "created_at"),
    ("echospell_groups", "EchoSpell groups finished", "echospell.GroupProgress", "completed_at"),
    ("tricks", "Tricks activities", "tricks.LessonActivityAttempt", "created_at"),
    ("assessments", "Assessments taken", "assessments.Attempt", "started_at"),
    ("clash", "Diction Clash games", "clash.Match", "started_at"),
    ("tutor", "Reading tutor sessions", "tutor.TutorSession", "started_at"),
    ("modules", "Module days finished", "learning_modules.DayProgress", "completed_at"),
    ("reading", "Reading Club chapters", "reading_club.ChapterProgress", "completed_at"),
]


# ---------------------------------------------------------------------------
# The period
# ---------------------------------------------------------------------------

def _tz():
    return ZoneInfo(settings.TIME_ZONE)


def _parse_day(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _earliest():
    candidates = [
        User.objects.aggregate(d=Min("date_joined"))["d"],
        Payment.objects.aggregate(d=Min("created_at"))["d"],
        School.objects.aggregate(d=Min("created_at"))["d"],
    ]
    found = [d for d in candidates if d]
    return min(found) if found else timezone.now()


class Period:
    """[start, end) in local time, the one before it, and the bucket size."""

    def __init__(self, params):
        tz = _tz()
        today = timezone.localdate()
        preset = params.get("range") or DEFAULT_PRESET
        start_day, end_day = _parse_day(params.get("from")), _parse_day(params.get("to"))

        if start_day and end_day:
            if end_day < start_day:
                start_day, end_day = end_day, start_day
            preset = "custom"
            self.label = f"{start_day:%d %b %Y} – {end_day:%d %b %Y}"
        else:
            if preset not in PRESETS:
                preset = DEFAULT_PRESET
            label, days = PRESETS[preset]
            self.label = label
            end_day = today
            if days is None:
                start_day = timezone.localtime(_earliest()).date()
            else:
                start_day = today - timedelta(days=days - 1)

        self.preset = preset
        self.start_day, self.end_day = start_day, end_day
        self.start = datetime.combine(start_day, time.min, tzinfo=tz)
        self.end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=tz)
        length = self.end - self.start
        self.prev_start, self.prev_end = self.start - length, self.start
        self.days = length.days

        grain = params.get("grain") or "auto"
        if grain not in GRAINS:
            grain = "day" if self.days <= 45 else "week" if self.days <= 200 else "month"
        self.grain = grain
        self.buckets = self._buckets(self.start, self.end)
        self.prev_buckets = self._buckets(self.prev_start, self.prev_end)

    def _floor(self, moment):
        local = timezone.localtime(moment, _tz())
        d = local.date()
        if self.grain == "week":
            d -= timedelta(days=d.weekday())
        elif self.grain == "month":
            d = d.replace(day=1)
        return d

    def _step(self, d):
        if self.grain == "day":
            return d + timedelta(days=1)
        if self.grain == "week":
            return d + timedelta(days=7)
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)

    def _buckets(self, start, end):
        out, d = [], self._floor(start)
        last = self._floor(end - timedelta(microseconds=1))
        while d <= last:
            out.append(d)
            d = self._step(d)
        return out

    def bucket_label(self, d):
        if self.grain == "month":
            return f"{d:%b %Y}"
        if self.grain == "week":
            return f"w/c {d.day} {d:%b}"
        return f"{d.day} {d:%b}"

    def series(self, queryset, field, value=None, previous=False):
        """Per-bucket totals: a count, or the sum of `value`."""
        start, end = (self.prev_start, self.prev_end) if previous else (self.start, self.end)
        buckets = self.prev_buckets if previous else self.buckets
        rows = (
            queryset.filter(**{f"{field}__gte": start, f"{field}__lt": end})
            .annotate(b=GRAINS[self.grain](field, tzinfo=_tz()))
            .values("b")
            .annotate(v=Sum(value) if value else Count("pk"))
        )
        found = {}
        for row in rows:
            key = row["b"].date() if isinstance(row["b"], datetime) else row["b"]
            found[key] = found.get(key, 0) + (row["v"] or 0)
        return [found.get(b, 0) for b in buckets]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _in(queryset, field, start, end):
    return queryset.filter(**{f"{field}__gte": start, f"{field}__lt": end})


def _change(now, before):
    """Percentage change, or None when there's nothing to compare with."""
    if not before:
        return None
    return round((now - before) / before * 100, 1)


def _naira(kobo):
    return round((kobo or 0) / 100, 2)


def _model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def _paid(queryset=None):
    """Money that actually came in: successful and more than ₦0."""
    queryset = Payment.objects.all() if queryset is None else queryset
    return queryset.filter(status=Payment.STATUS_SUCCESS, amount__gt=0)


def _audience_of(payment):
    if payment.plan_id and payment.plan:
        return payment.plan.audience
    sub = payment.subscription
    if sub is not None and sub.school_id:
        return Plan.AUDIENCE_SCHOOL
    payer = payment.payer
    if payer is not None and payer.role == "student":
        return Plan.AUDIENCE_STUDENT
    return Plan.AUDIENCE_INDIVIDUAL


def _kpi(key, label, now, before, series, fmt="number", hint="", up_is_good=True):
    return {
        "key": key, "label": label, "value": now, "previous": before,
        "change": _change(now, before), "series": series, "format": fmt,
        "hint": hint, "up_is_good": up_is_good,
    }


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def build(params):
    p = Period(params)
    now = timezone.now()
    labels = [p.bucket_label(b) for b in p.buckets]

    paid = _paid()
    paid_now, paid_before = _in(paid, "paid_at", p.start, p.end), _in(paid, "paid_at", p.prev_start, p.prev_end)
    revenue_now = paid_now.aggregate(s=Sum("amount"))["s"] or 0
    revenue_before = paid_before.aggregate(s=Sum("amount"))["s"] or 0
    revenue_series = [_naira(v) for v in p.series(paid, "paid_at", "amount")]
    revenue_prev_series = [_naira(v) for v in p.series(paid, "paid_at", "amount", previous=True)]
    count_now, count_before = paid_now.count(), paid_before.count()

    users = User.objects.filter(is_staff=False)
    joined_now = _in(users, "date_joined", p.start, p.end)
    joined_before = _in(users, "date_joined", p.prev_start, p.prev_end)
    role_series = {role: p.series(users.filter(role=role), "date_joined") for role in ROLE_LABELS}
    schools_series = p.series(School.objects.all(), "created_at")
    schools_now = _in(School.objects.all(), "created_at", p.start, p.end).count()
    schools_before = _in(School.objects.all(), "created_at", p.prev_start, p.prev_end).count()

    def role_counts(qs):
        return dict(qs.values_list("role").annotate(n=Count("pk")))

    roles_now, roles_before = role_counts(joined_now), role_counts(joined_before)

    # Learning activity, and the learners behind it.
    activity, active_now, active_before = [], set(), set()
    for key, label, model_label, field in ACTIVITY_SOURCES:
        model = _model(model_label)
        if model is None:
            continue
        qs = model.objects.all()
        series = p.series(qs, field)
        now_qs, before_qs = _in(qs, field, p.start, p.end), _in(qs, field, p.prev_start, p.prev_end)
        active_now.update(now_qs.values_list("user_id", flat=True))
        active_before.update(before_qs.values_list("user_id", flat=True))
        activity.append({"key": key, "label": label, "values": series, "total": sum(series)})
    active_now.discard(None)
    active_before.discard(None)
    activity_total = [sum(col) for col in zip(*[a["values"] for a in activity])] if activity else [0] * len(labels)
    active_series = _active_learner_series(p)

    # Subscriptions right now.
    subs = Subscription.objects.select_related("plan")
    state = {"school": {"active": 0, "trial": 0, "expired": 0}, "learner": {"active": 0, "trial": 0, "expired": 0}}
    for sub in subs:
        state["school" if sub.school_id else "learner"][sub.state(now)] += 1
    paying_now = state["school"]["active"] + state["learner"]["active"]

    # Trial to paid: accounts that started in the period and have paid since.
    started = _in(Subscription.objects.all(), "created_at", p.start, p.end)
    converted = started.filter(payments__status=Payment.STATUS_SUCCESS, payments__amount__gt=0).distinct().count()
    started_n = started.count()
    started_before = _in(Subscription.objects.all(), "created_at", p.prev_start, p.prev_end)
    converted_before = started_before.filter(payments__status=Payment.STATUS_SUCCESS, payments__amount__gt=0).distinct().count()
    conv_now = round(converted / started_n * 100, 1) if started_n else 0
    conv_before = round(converted_before / started_before.count() * 100, 1) if started_before.count() else 0

    accounts_paying = paid_now.values("subscription").distinct().count()
    arpa_now = _naira(revenue_now / accounts_paying) if accounts_paying else 0
    accounts_before = paid_before.values("subscription").distinct().count()
    arpa_before = _naira(revenue_before / accounts_before) if accounts_before else 0

    kpis = [
        _kpi("revenue", "Revenue", _naira(revenue_now), _naira(revenue_before), revenue_series, "naira",
             "Successful payments in the period. Free grants aren't counted."),
        _kpi("payments", "Paid payments", count_now, count_before, p.series(paid, "paid_at")),
        _kpi("arpa", "Average per paying account", arpa_now, arpa_before, [], "naira"),
        _kpi("schools", "New schools", schools_now, schools_before, schools_series),
        _kpi("adults", "New adult learners", roles_now.get("individual", 0), roles_before.get("individual", 0), role_series["individual"]),
        _kpi("students", "New students", roles_now.get("student", 0), roles_before.get("student", 0), role_series["student"]),
        _kpi("teachers", "New teachers", roles_now.get("teacher", 0), roles_before.get("teacher", 0), role_series["teacher"]),
        _kpi("active", "Active learners", len(active_now), len(active_before), active_series,
             hint="Learners who did at least one activity in the period."),
        _kpi("conversion", "Trial to paid", conv_now, conv_before, [], "percent",
             hint="Of the accounts that started in the period, the share that have paid."),
    ]

    # Where the money comes from.
    by_audience, by_plan, by_channel = {}, {}, {}
    for pay in paid_now.select_related("plan", "subscription", "payer"):
        aud = AUDIENCE_LABELS.get(_audience_of(pay), "Other")
        by_audience[aud] = by_audience.get(aud, 0) + pay.amount
        by_plan[pay.plan_name or "Unknown plan"] = by_plan.get(pay.plan_name or "Unknown plan", 0) + pay.amount
        channel = (pay.channel or "unknown").replace("_", " ")
        channel = "USSD" if channel == "ussd" else channel.capitalize()
        by_channel[channel] = by_channel.get(channel, 0) + 1

    def ranked(d, money=True, top=8):
        items = sorted(d.items(), key=lambda kv: -kv[1])
        if len(items) > top:
            rest = sum(v for _k, v in items[top - 1:])
            items = items[: top - 1] + [("Other", rest)]
        return [{"label": k, "value": _naira(v) if money else v} for k, v in items]

    attempts = _in(Payment.objects.all(), "created_at", p.start, p.end)
    health = dict(attempts.values_list("status").annotate(n=Count("pk")))
    grants = _in(Payment.objects.filter(status=Payment.STATUS_SUCCESS, amount=0), "paid_at", p.start, p.end)
    promo = _in(PromoRedemption.objects.all(), "created_at", p.start, p.end)
    promo_rows = list(promo.values("promo__code").annotate(n=Count("pk"), off=Sum("amount_off")).order_by("-off")[:8])

    # Learners by level (right now): ordered as the levels themselves are.
    from apps.accounts.access import LEVEL_ORDER
    level_counts = dict(users.filter(role="student").exclude(level="").values_list("level").annotate(n=Count("pk")))
    levels = [{"label": lv, "value": level_counts.get(lv, 0)} for lv in LEVEL_ORDER if level_counts.get(lv)]
    unlevelled = users.filter(role="student", level="").count()
    if unlevelled:
        levels.append({"label": "No level yet", "value": unlevelled})

    totals = {
        "revenue_all": _naira(paid.aggregate(s=Sum("amount"))["s"]),
        "schools": School.objects.count(),
        "adults": users.filter(role="individual").count(),
        "students": users.filter(role="student").count(),
        "teachers": users.filter(role="teacher").count(),
        "paying": paying_now,
    }

    return {
        "period": {
            "preset": p.preset, "label": p.label, "grain": p.grain, "days": p.days,
            "from": p.start_day.isoformat(), "to": p.end_day.isoformat(),
            "prev_label": f"{timezone.localtime(p.prev_start):%d %b} – {timezone.localtime(p.prev_end - timedelta(seconds=1)):%d %b %Y}",
        },
        "presets": [{"key": k, "label": v[0]} for k, v in PRESETS.items()],
        "labels": labels,
        "kpis": kpis,
        "totals": totals,
        "revenue": {"current": revenue_series, "previous": revenue_prev_series},
        "signups": {
            "series": [{"key": r, "label": ROLE_LABELS[r], "values": role_series[r]} for r in ROLE_LABELS],
            "schools": schools_series,
        },
        "activity": {"series": activity, "total": activity_total},
        "breakdowns": {
            "audience": ranked(by_audience),
            "plans": ranked(by_plan),
            "channels": ranked(by_channel, money=False),
            "levels": levels,
        },
        "subscriptions": state,
        "health": {
            "success": health.get(Payment.STATUS_SUCCESS, 0),
            "failed": health.get(Payment.STATUS_FAILED, 0),
            "abandoned": health.get(Payment.STATUS_ABANDONED, 0),
            "pending": health.get(Payment.STATUS_PENDING, 0),
            "grants": grants.count(),
            "discount": _naira(promo.aggregate(s=Sum("amount_off"))["s"]),
            "promos": [{"code": r["promo__code"], "uses": r["n"], "off": _naira(r["off"])} for r in promo_rows],
        },
        "schools": _top_schools(p),
        "payments": _recent_payments(p),
    }


def _active_learner_series(p):
    """Distinct learners active in each bucket."""
    per_bucket = [set() for _ in p.buckets]
    index = {b: i for i, b in enumerate(p.buckets)}
    for _key, _label, model_label, field in ACTIVITY_SOURCES:
        model = _model(model_label)
        if model is None:
            continue
        rows = (
            _in(model.objects.all(), field, p.start, p.end)
            .annotate(b=GRAINS[p.grain](field, tzinfo=_tz()))
            .values_list("b", "user_id").distinct()
        )
        for bucket, user_id in rows:
            key = bucket.date() if isinstance(bucket, datetime) else bucket
            if key in index and user_id:
                per_bucket[index[key]].add(user_id)
    return [len(s) for s in per_bucket]


def _top_schools(p):
    schools = School.objects.annotate(
        teacher_n=Count("members", filter=Q(members__role="teacher"), distinct=True),
        student_n=Count("members", filter=Q(members__role="student"), distinct=True),
    )
    paid = _paid()
    revenue_all = dict(
        paid.filter(subscription__school__isnull=False)
        .values_list("subscription__school").annotate(s=Sum("amount"))
    )
    revenue_period = dict(
        _in(paid, "paid_at", p.start, p.end).filter(subscription__school__isnull=False)
        .values_list("subscription__school").annotate(s=Sum("amount"))
    )
    rows = []
    for school in schools:
        plan = school.paid_plan()
        sub = getattr(school, "subscription", None)
        rows.append({
            "name": school.name,
            "code": school.code,
            "joined": timezone.localtime(school.created_at).date().isoformat(),
            "teachers": school.teacher_n,
            "students": school.student_n,
            "limit": school.teacher_limit,
            "plan": f"{plan.name}{f' · {plan.band_label}' if plan.band_label else ''}" if plan else "",
            "state": sub.state() if sub else "none",
            "until": timezone.localtime(sub.access_until).date().isoformat() if sub and sub.access_until else "",
            "revenue_period": _naira(revenue_period.get(school.pk, 0)),
            "revenue_all": _naira(revenue_all.get(school.pk, 0)),
        })
    rows.sort(key=lambda r: (-r["revenue_all"], -r["students"], r["name"]))
    return rows[:50]


def _recent_payments(p):
    rows = []
    qs = (
        _in(Payment.objects.all(), "created_at", p.start, p.end)
        .select_related("plan", "subscription__school", "payer").order_by("-created_at")[:100]
    )
    for pay in qs:
        rows.append({
            "when": timezone.localtime(pay.paid_at or pay.created_at).strftime("%Y-%m-%d %H:%M"),
            "account": pay.account_name,
            "email": pay.email,
            "type": AUDIENCE_LABELS.get(_audience_of(pay), "Other"),
            "plan": pay.plan_name,
            "amount": _naira(pay.amount),
            "discount": _naira(pay.discount),
            "channel": pay.channel or "",
            "status": pay.get_status_display(),
            "reference": pay.reference,
        })
    return rows
