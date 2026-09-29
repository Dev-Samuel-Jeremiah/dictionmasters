"""
Control room > Schools & people: every school at a glance, and each
school's teachers, students and admins with their details.

    /manage/schools-directory/           every school (and individual learners)
    /manage/schools-directory/<pk>/      one school's people; 0 = individual learners
                                          ?role=, ?level=, ?q=, ?csv=1 to download
"""

import csv
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts import access
from apps.accounts.models import User
from apps.echospell.models import LEVEL_NAME_CHOICES
from apps.schools.models import School

LEVEL_ORDER = [value for value, _label in LEVEL_NAME_CHOICES]

PER_PAGE = 50
ROLES = [
    ("", "Everyone"), ("teacher", "Teachers"), ("student", "Students"),
    ("school_admin", "School admins"), ("removed", "Removed"),
]


def _plan_state(school):
    """(label, tone) for the school's plan: paid, on trial, or ended."""
    subscription = getattr(school, "subscription", None)
    if subscription is None:
        return "No plan yet", "muted"
    now = timezone.now()
    state = subscription.state(now)
    plan = subscription.plan.name if subscription.plan_id else ""
    if state == subscription.STATE_ACTIVE:
        return f"{plan or 'Paid'} · until {timezone.localtime(subscription.paid_until):%d %b %Y}", "good"
    if state == subscription.STATE_TRIAL:
        days = subscription.days_left(now)
        return f"Free trial · {days} day{'s' if days != 1 else ''} left" + (f" ({plan})" if plan else ""), "trial"
    return "Access ended" + (f" · {plan}" if plan else ""), "bad"


def directory(request):
    query = request.GET.get("q", "").strip()
    active = Q(members__is_active=True)
    schools = (
        School.objects.select_related("subscription__plan")
        .annotate(
            teacher_n=Count("members", filter=active & Q(members__role="teacher"), distinct=True),
            student_n=Count("members", filter=active & Q(members__role="student"), distinct=True),
            admin_n=Count("members", filter=active & Q(members__role="school_admin"), distinct=True),
            removed_n=Count("members", filter=Q(members__is_active=False, members__role__in=("teacher", "student")), distinct=True),
            last_seen=Max("members__last_login"),
        )
        .order_by("name")
    )
    if query:
        schools = schools.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(email__icontains=query))
    rows = []
    for school in schools:
        label, tone = _plan_state(school)
        rows.append({"school": school, "plan": label, "tone": tone, "teacher_limit": school.teacher_limit})
    individuals = User.objects.filter(school__isnull=True, role=User.Role.INDIVIDUAL, is_staff=False)
    totals = {
        "schools": School.objects.count(),
        "teachers": User.objects.filter(role="teacher", is_active=True).count(),
        "students": User.objects.filter(role="student", is_active=True).count(),
        "individuals": individuals.filter(is_active=True).count(),
    }
    return {"rows": rows, "query": query, "totals": totals,
            "individual_count": totals["individuals"], "individual_last": individuals.aggregate(m=Max("last_login"))["m"]}


def people(request, pk):
    """One school's people (pk 0: individual learners, who have no school)."""
    if pk == 0:
        school = None
        members = User.objects.filter(school__isnull=True, role=User.Role.INDIVIDUAL, is_staff=False)
    else:
        school = School.objects.select_related("subscription__plan").filter(pk=pk).first()
        if school is None:
            raise Http404("No such school.")
        members = User.objects.filter(school=school)

    role = request.GET.get("role", "")
    level = request.GET.get("level", "")
    query = request.GET.get("q", "").strip()
    shown = members
    if role == "removed":
        shown = shown.filter(is_active=False)
    elif role:
        shown = shown.filter(role=role, is_active=True)
    if level:
        # A teacher given several levels from the control room shows up
        # under each of them, not just their main one.
        shown = access.in_level(shown, level)
    if query:
        shown = shown.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query)
                             | Q(email__icontains=query) | Q(username__icontains=query))
    order = {"role": ["role", "first_name"], "name": ["first_name", "last_name"], "joined": ["-date_joined"],
             "seen": ["-last_login"], "level": ["level", "first_name"]}.get(request.GET.get("sort", ""), ["role", "first_name", "last_name"])
    shown = shown.order_by(*order)

    if request.GET.get("csv"):
        return _csv(school, shown)

    active = members.filter(is_active=True)
    by_role = {r: active.filter(role=r).count() for r in ("teacher", "student", "school_admin")}

    # Every level anyone here has, as a main level or an extra one — so a
    # teacher given several levels shows up, and can be filtered on, under
    # each of them, not just their first.
    present = {lvl for lvl in active.exclude(level="").values_list("level", flat=True)}
    for extra in active.exclude(additional_levels="").values_list("additional_levels", flat=True):
        present.update(v for v in extra.split(",") if v)
    present = sorted(present, key=lambda v: LEVEL_ORDER.index(v) if v in LEVEL_ORDER else len(LEVEL_ORDER))
    levels = []
    for lvl in present:
        in_lvl = access.in_level(active, lvl)
        levels.append({"level": lvl, "students": in_lvl.filter(role="student").count(),
                       "teachers": in_lvl.filter(role="teacher").count()})
    top = max([l["students"] for l in levels] or [1]) or 1
    for l in levels:
        l["width"] = round(l["students"] * 100 / top)
    week_ago = timezone.now() - timedelta(days=7)
    page = Paginator(shown, PER_PAGE).get_page(request.GET.get("page"))
    context = {
        "school": school,
        "page": page,
        "total_shown": shown.count(),
        "role": role, "level": level, "query": query, "sort": request.GET.get("sort", ""),
        "roles": ROLES if school else [("", "Everyone"), ("removed", "Switched off")],
        "level_options": present,
        "by_role": by_role,
        "removed_n": members.filter(is_active=False).count(),
        "active_week": active.filter(last_login__gte=week_ago).count(),
        "never_signed_in": active.filter(last_login__isnull=True).count(),
        "levels": levels,
    }
    if school:
        label, tone = _plan_state(school)
        context.update(plan=label, tone=tone, teacher_limit=school.teacher_limit)
    return context


def _csv(school, members):
    stamp = timezone.localtime()
    name = slugify(school.name) if school else "individual-learners"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}-people-{stamp:%Y-%m-%d}.csv"'
    response.write("﻿")                               # opens cleanly in Excel
    out = csv.writer(response)
    out.writerow(["First name", "Last name", "Role", "Level", "Signs in with", "Email", "Joined", "Last signed in", "Status"])
    for m in members:
        out.writerow([
            m.first_name, m.last_name, m.get_role_display(), m.level_display, m.login_name,
            m.email if m.has_real_email else "",
            timezone.localtime(m.date_joined).strftime("%Y-%m-%d"),
            timezone.localtime(m.last_login).strftime("%Y-%m-%d %H:%M") if m.last_login else "Never",
            "Active" if m.is_active else "Removed",
        ])
    return response
