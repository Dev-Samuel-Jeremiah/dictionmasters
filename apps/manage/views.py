"""
The control room: one set of screens that manages every part of Diction
Masters, built from the registry.

There are only five real pages — a home page, a list, a form, a delete
confirmation and a search — and they work for all 40-odd kinds of
content, so every screen behaves exactly the same way. Anyone who has
learned one has learned them all.

Staff accounts only, with the control room's own sign-in page.
"""

import json
from datetime import timedelta
from functools import wraps

from django import forms
from django.apps import apps as django_apps
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.book import phoneme_audio, video_poster
from apps.echospell import importer as echospell_importer
from apps.echospell.models import Group, Level
from apps.console import jobs
from apps.console.dashboard import console_context
from apps.billing import paystack
from apps.book import read_along as book_read_along
from apps.book.models import ReadAlongTiming
from apps.billing.models import BillingSettings
from apps.billing.services import CheckoutError, grant_plan, grant_school_plan
from apps.landing.models import SiteBranding
from apps.quick_words.audio_zip import start_audio_zip_import
from apps.quick_words.models import QuickWordAudioImportJob

from .forms import ControlLoginForm, QuickWordAudioZipForm, SchoolTrialForm, LearnerTrialForm, EditTrialForm, build_form
from . import analytics
from .level_field import add_levels_field, save_levels
from .plan_field import FIELD as PLAN_FIELD, add_plan_field, check_plan
from .school_login import add_login_fields, check_login, save_login
from .bulk_questions import question_formset
from . import results
from .kind_fields import guide
from .registry import QUICK_ADDS, SECTIONS, get_screen, screens

PER_PAGE = 25


# ---------------------------------------------------------------------------
# Getting in
# ---------------------------------------------------------------------------

def staff_only(view):
    """Only staff see the control room. Everyone else is sent to its own
    sign-in page, not the learners' one."""

    @wraps(view)
    def guard(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect(f"{reverse('manage:login')}?next={request.path}")
        return view(request, *args, **kwargs)

    return guard


def login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("manage:home")

    form = ControlLoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        target = request.GET.get("next") or reverse("manage:home")
        return redirect(target if target.startswith("/") else reverse("manage:home"))

    return render(request, "manage/login.html", {"form": form})


@staff_only
def logout_view(request):
    auth_logout(request)
    return redirect("manage:login")


# ---------------------------------------------------------------------------
# Helpers shared by every screen
# ---------------------------------------------------------------------------

def _model_for(screen):
    return django_apps.get_model(screen["model"])


def _default_value(value):
    """A screen's default, where a few are worked out when saving."""
    if value == "book.tricks_group":
        from apps.book.models import SoundCategory

        return SoundCategory.for_tricks()
    return value


def _rows_for(screen):
    """The records that belong to a screen. Some screens share a table and
    see only their part of it, e.g. 44 Academy's sounds and the tricks."""
    return _model_for(screen).objects.filter(**screen.get("where", {}))


def _search_condition(model, fields, query):
    """A search across the fields a model really has, so a rename in the
    models can never take a page down."""
    names = {f.name for f in model._meta.get_fields()}
    condition = Q()
    used = False
    for field in fields:
        if field.split("__")[0] not in names:
            continue
        condition |= Q(**{f"{field}__icontains": query})
        used = True
    return condition if used else None


def _screen_or_404(key):
    screen = get_screen(key)
    if screen is None:
        raise Http404("No such screen.")
    return screen


def _title(screen):
    model = _model_for(screen)
    return screen.get("name") or str(model._meta.verbose_name_plural).capitalize()


def _singular(screen):
    return screen.get("singular") or str(_model_for(screen)._meta.verbose_name)


def _cell(obj, column):
    """One value for the list, ready to show."""
    value = getattr(obj, column, "")
    if callable(value):
        value = value()
    if hasattr(value, "name") and hasattr(value, "storage"):  # a file or image
        if not value or not value.name:
            return {"kind": "blank"}
        try:
            url = value.url
        except ValueError:  # a cleared or otherwise empty FileField
            return {"kind": "blank"}
        return {"kind": "file", "text": value.name.rsplit("/", 1)[-1], "url": url}
    if isinstance(value, bool):
        return {"kind": "bool", "on": value}
    if value is None or value == "":
        return {"kind": "blank"}
    if hasattr(value, "isoformat"):
        return {"kind": "when", "text": value}
    return {"kind": "text", "text": str(value)}


def _sections_for_nav(current_key=None):
    nav = []
    for section in SECTIONS:
        items = []
        for screen in section["screens"]:
            items.append({
                "key": screen["key"],
                "name": _title(screen),
                "count": _rows_for(screen).count(),
                "current": screen["key"] == current_key,
            })
        nav.append({**section, "items": items, "open": any(i["current"] for i in items)})
    return nav


def _record(request, obj, action, message):
    """Keep the same history the Django admin writes, so one list shows
    every change however it was made."""
    LogEntry.objects.log_action(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk,
        object_repr=str(obj)[:200],
        action_flag=action,
        change_message=message,
    )


def _base_context(request, current_key=None, **extra):
    return {
        "nav": _sections_for_nav(current_key),
        "current_key": current_key,
        "to_mark": results.to_mark_count(),
        **extra,
    }


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@staff_only
def home(request):
    console = console_context(request)["console"]
    quick = []
    for key, name, icon in QUICK_ADDS:
        screen = get_screen(key)
        if screen and not screen.get("readonly"):
            quick.append({"name": name, "icon": icon, "url": reverse("manage:add", args=[key])})

    sections = []
    for section in SECTIONS:
        rows = []
        for screen in section["screens"]:
            rows.append({
                "key": screen["key"],
                "name": _title(screen),
                "count": _rows_for(screen).count(),
                "readonly": screen.get("readonly", False),
            })
        sections.append({**section, "rows": rows})

    return render(request, "manage/home.html", _base_context(
        request,
        stats=console["stats"],
        attention=console["attention"],
        services=console["services"],
        recent=console["recent"],
        greeting=console["greeting"],
        quick=quick,
        sections=sections,
    ))


@staff_only
def search(request):
    """One box across every screen."""
    query = request.GET.get("q", "").strip()
    groups = []
    if query:
        for key, screen in screens().items():
            fields = screen.get("search") or []
            if not fields:
                continue
            model = _model_for(screen)
            condition = _search_condition(model, fields, query)
            if condition is None:
                continue
            found = list(_rows_for(screen).filter(condition)[:6])
            if found:
                groups.append({
                    "key": key,
                    "name": _title(screen),
                    "icon": screen["section"]["icon"],
                    "readonly": screen.get("readonly", False),
                    "rows": [{"pk": o.pk, "label": str(o)} for o in found],
                })
    return render(request, "manage/search.html", _base_context(
        request, query=query, groups=groups, total=sum(len(g["rows"]) for g in groups)
    ))


# ---------------------------------------------------------------------------
# Quick Words: bulk audio upload
# ---------------------------------------------------------------------------

@staff_only
def quick_words_audio_upload(request):
    form = QuickWordAudioZipForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        job = QuickWordAudioImportJob.objects.create(
            uploaded_by=request.user,
            archive=form.cleaned_data["audio_zip"],
            total_files=form.audio_count,
        )
        start_audio_zip_import(job.pk)
        return redirect("manage:quick_words_audio_import", job_id=job.pk)

    return render(request, "manage/quick_words_upload.html", _base_context(
        request, "words", form=form,
    ))


@staff_only
def quick_words_audio_import(request, job_id):
    job = get_object_or_404(QuickWordAudioImportJob, pk=job_id, uploaded_by=request.user)
    return render(request, "manage/quick_words_upload.html", _base_context(
        request, "words", job=job,
    ))


# ---------------------------------------------------------------------------
# One kind of thing: list, add, edit, delete
# ---------------------------------------------------------------------------

@staff_only
def record_list(request, key):
    screen = _screen_or_404(key)
    model = _model_for(screen)
    rows = _rows_for(screen)

    # Opened from inside its parent, e.g. the groups of one level.
    parent_obj = None
    parent_key = None
    if screen.get("parent") and request.GET.get("in"):
        field, parent_key = screen["parent"]
        parent_obj = _rows_for(_screen_or_404(parent_key)).filter(pk=request.GET["in"]).first()
        if parent_obj:
            rows = rows.filter(**{field: parent_obj})

    query = request.GET.get("q", "").strip()
    if query and screen.get("search"):
        condition = _search_condition(model, screen["search"], query)
        if condition is not None:
            rows = rows.filter(condition)

    if screen.get("order"):
        rows = rows.order_by(*screen["order"])

    columns = screen["columns"]
    page = Paginator(rows, PER_PAGE).get_page(request.GET.get("page"))
    table = [
        {"pk": obj.pk, "label": str(obj), "cells": [_cell(obj, c) for c in columns]}
        for obj in page.object_list
    ]

    headings = []
    for column in columns:
        try:
            headings.append(str(model._meta.get_field(column).verbose_name).capitalize())
        except Exception:
            headings.append(column.replace("_", " ").replace("__str__", "Name").strip().capitalize())
    for row in table:
        for heading, cell in zip(headings, row["cells"]):
            cell["heading"] = heading

    return render(request, "manage/list.html", _base_context(
        request, key,
        screen=screen, title=_title(screen), singular=_singular(screen),
        headings=headings, rows=table, page=page, query=query,
        parent_obj=parent_obj, parent_key=parent_key,
        readonly=screen.get("readonly", False), total=rows.count(),
        wide_list=screen["key"] == "schools",
        deletable=not screen.get("readonly") and not screen.get("no_delete"),
        bulk_url=(reverse("manage:bulk_questions", args=[key]) + (f"?in={parent_obj.pk}" if parent_obj else ""))
        if screen.get("bulk_add") else "",
    ))


@staff_only
def record_form(request, key, pk=None):
    screen = _screen_or_404(key)
    model = _model_for(screen)
    if screen.get("readonly"):
        messages.info(request, f"{_title(screen)} are written by the site itself, so they can only be viewed.")
        return redirect("manage:list", key=key)
    if screen.get("no_add") and not pk:
        messages.info(request, f"These { _title(screen).lower()} are fixed; use the existing records.")
        return redirect("manage:list", key=key)

    obj = get_object_or_404(_rows_for(screen), pk=pk) if pk else None

    # Adding something inside its parent: the link is set for you.
    parent_field = parent_obj = None
    if screen.get("parent"):
        field, parent_key = screen["parent"]
        chosen = request.GET.get("in") or request.POST.get("_in")
        if chosen:
            parent_obj = _rows_for(_screen_or_404(parent_key)).filter(pk=chosen).first()
            if parent_obj:
                parent_field = field

    FormClass = build_form(model, screen.get("form"), exclude_parent=parent_field if not pk else None)
    form = FormClass(request.POST or None, request.FILES or None, instance=obj)
    for name, (label, help_text) in screen.get("labels", {}).items():
        if name in form.fields:
            form.fields[name].label, form.fields[name].help_text = label, help_text
    # Levels as a tick-list, so one person — a teacher who covers several,
    # say — can be given more than just one.
    if screen.get("levels_field"):
        add_levels_field(form, obj)
    # Dropdowns offer only what belongs here, e.g. a trick's group is a trick group.
    for name, condition in screen.get("limit", {}).items():
        if name in form.fields and hasattr(form.fields[name], "queryset"):
            form.fields[name].queryset = form.fields[name].queryset.filter(**condition)
    # Activities: only the fields their type needs (apps/manage/kind_fields.py).
    kind_guide = guide(screen, form, obj=obj, parent_obj=parent_obj)
    plan_kind = screen.get("plan_field")
    if plan_kind:
        add_plan_field(form, obj, plan_kind)
    login_fields = screen.get("login_fields")
    if login_fields:
        add_login_fields(form, obj)

    if (request.method == "POST" and form.is_valid()
            and (not plan_kind or check_plan(form, obj, plan_kind))
            and (not login_fields or check_login(form, obj))):
        saved = form.save(commit=False)
        if parent_field and parent_obj and not pk:
            setattr(saved, parent_field, parent_obj)
        if not pk:
            for name, value in screen.get("defaults", {}).items():
                setattr(saved, name, _default_value(value))
        with transaction.atomic():
            saved.save()
            form.save_m2m()
            if screen.get("levels_field"):
                save_levels(form, saved)
            login_note = save_login(saved, form) if login_fields else ""
        _record(request, saved, CHANGE if pk else ADDITION, "Changed in the control room" if pk else "Added in the control room")
        messages.success(request, f"{_singular(screen).capitalize()} “{saved}” {'updated' if pk else 'added'}.")
        if login_note:
            messages.success(request, login_note)
        plan = form.cleaned_data.get(PLAN_FIELD) if plan_kind else None
        if plan is not None:
            try:
                if plan_kind == "school":
                    payment = grant_school_plan(saved, plan, granted_by=request.user)
                else:
                    payment = grant_plan(saved, plan, granted_by=request.user)
            except CheckoutError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"{plan.name} given: access runs until {timezone.localtime(payment.period_end):%d %b %Y}.")
        if "_again" in request.POST:
            again = reverse("manage:add", args=[key])
            return redirect(f"{again}?in={parent_obj.pk}" if parent_obj else again)
        if parent_obj:
            return redirect(f"{reverse('manage:edit', args=[screen['parent'][1], parent_obj.pk])}")
        return redirect("manage:list", key=key)

    # What lives inside this one, e.g. the groups of a level.
    children = []
    if obj is not None:
        for child_key in screen.get("children", []):
            child = get_screen(child_key)
            if not child:
                continue
            field = child["parent"][0]
            found = _rows_for(child).filter(**{field: obj})
            if child.get("order"):
                found = found.order_by(*child["order"])
            children.append({
                "key": child_key,
                "name": _title(child),
                "singular": _singular(child),
                "rows": [{"pk": c.pk, "label": str(c)} for c in found[:50]],
                "count": found.count(),
                "add_url": f"{reverse('manage:add', args=[child_key])}?in={obj.pk}",
                "bulk_url": reverse(child["bulk_view"], args=[obj.pk]) if child.get("bulk_view") else (
                    f"{reverse('manage:bulk_questions', args=[child_key])}?in={obj.pk}" if child.get("bulk_add") else ""),
                "bulk_label": child.get("bulk_label", "+ Add multiple"),
                "list_url": f"{reverse('manage:list', args=[child_key])}?in={obj.pk}",
            })

    bulk_activity_id = parent_obj.pk if parent_obj else getattr(obj, "activity_id", None)
    bulk_url = reverse("manage:bulk_questions", args=[key]) if screen.get("bulk_add") else ""
    if bulk_url and bulk_activity_id:
        bulk_url += f"?in={bulk_activity_id}"

    return render(request, "manage/form.html", _base_context(
        request, key,
        screen=screen, form=form, obj=obj, title=_title(screen), singular=_singular(screen),
        parent_obj=parent_obj, children=children,
        kind_guide=kind_guide, bulk_url=bulk_url,
    ))


@staff_only
def bulk_questions(request, key):
    """Add a batch of Tricks assessment questions to one activity."""
    screen = _screen_or_404(key)
    if not screen.get("bulk_add") or not screen.get("parent"):
        raise Http404("Bulk question entry is not available for this screen.")

    activity_key = screen["parent"][1]
    activity_screen = _screen_or_404(activity_key)
    activities = _rows_for(activity_screen).select_related("lesson").order_by(
        "lesson__category__order", "lesson__order", "order", "id"
    )
    raw_activity_id = request.POST.get("activity") if request.method == "POST" else request.GET.get("in")
    activity_id = None
    activity = None
    if raw_activity_id:
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            activity_id = None
        if activity_id is not None:
            activity = activities.filter(pk=activity_id).first()

    if request.method == "GET" and raw_activity_id and activity is None:
        raise Http404("No assessment activity found.")

    if activity is None:
        return render(request, "manage/bulk_questions.html", _base_context(
            request, key,
            screen=screen, title="Add multiple questions", activities=activities,
            selected_activity_id=activity_id,
            picker_error=("Choose a valid assessment activity." if request.method == "POST" else ""),
            activity=None,
        ))

    if not activity.kind_spec:
        raise Http404("This activity type is no longer available.")

    formset = question_formset(
        activity.kind_spec,
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and formset.is_valid():
        max_order = activity.items.aggregate(last_order=Max("order"))["last_order"]
        next_order = max_order + 1 if max_order is not None else 0
        added = 0
        with transaction.atomic():
            for item_form in formset:
                data = item_form.cleaned_data
                if not item_form.has_changed() or data.get("DELETE", False):
                    continue
                item_fields = {
                    name: data[name]
                    for name in ("prompt", "answer", "options", "hint", "audio_url", "audio_file", "image")
                    if name in data
                }
                item = _model_for(screen)(activity=activity, order=next_order, **item_fields)
                item.save()
                _record(request, item, ADDITION, "Added through bulk question entry")
                next_order += 1
                added += 1

        messages.success(request, f"Added {added} question{'s' if added != 1 else ''} to “{activity}”.")
        return redirect("manage:edit", key=activity_key, pk=activity.pk)

    return render(request, "manage/bulk_questions.html", _base_context(
        request, key,
        screen=screen, title="Add multiple questions", activities=activities,
        selected_activity_id=activity.pk, activity=activity, formset=formset,
        cancel_url=reverse("manage:edit", args=[activity_key, activity.pk]),
    ))


@staff_only
def record_delete(request, key, pk):
    screen = _screen_or_404(key)
    model = _model_for(screen)
    obj = get_object_or_404(_rows_for(screen), pk=pk)
    if screen.get("readonly") or screen.get("no_delete"):
        messages.info(request, f"{_title(screen)} cannot be deleted.")
        return redirect("manage:list", key=key)

    if request.method == "POST":
        label = str(obj)
        _record(request, obj, DELETION, "Deleted in the control room")
        obj.delete()
        messages.success(request, f"{_singular(screen).capitalize()} “{label}” deleted.")
        return redirect("manage:list", key=key)

    # What would go with it, so nothing is deleted by surprise.
    from django.contrib.admin.utils import NestedObjects
    from django.db import router

    collector = NestedObjects(using=router.db_for_write(model))
    collector.collect([obj])
    also = []
    for related_model, instances in collector.model_objs.items():
        if related_model is model:
            continue
        also.append({"name": str(related_model._meta.verbose_name_plural), "count": len(instances)})

    return render(request, "manage/delete.html", _base_context(
        request, key, screen=screen, obj=obj, title=_title(screen), singular=_singular(screen), also=also
    ))


@staff_only
@require_POST
def record_delete_many(request, key):
    """Delete the rows ticked on a list: first a page saying what goes (and
    what goes with it), then, once confirmed, all of them together."""
    from django.contrib.admin.utils import NestedObjects
    from django.db import router
    from django.db.models import ProtectedError

    screen = _screen_or_404(key)
    model = _model_for(screen)
    back = request.POST.get("next") or reverse("manage:list", args=[key])
    if not back.startswith("/manage/"):
        back = reverse("manage:list", args=[key])
    if screen.get("readonly") or screen.get("no_delete"):
        messages.info(request, f"{_title(screen)} cannot be deleted.")
        return redirect(back)

    from apps.accounts.models import User

    chosen = _rows_for(screen).filter(pk__in=request.POST.getlist("pk"))
    if model is User:
        # Never your own account, and never a superuser, from here.
        kept = chosen.filter(Q(pk=request.user.pk) | Q(is_superuser=True))
        if kept.exists():
            messages.warning(request, "Your own account and superuser accounts were left out: they can't be deleted from a list.")
        chosen = chosen.exclude(pk__in=kept.values("pk"))
    objs = list(chosen)
    if not objs:
        messages.info(request, "Nothing was selected to delete.")
        return redirect(back)

    if request.POST.get("confirm") == "yes":
        count = len(objs)
        try:
            with transaction.atomic():
                for obj in objs:
                    _record(request, obj, DELETION, "Deleted in the control room (several at once)")
                chosen.filter(pk__in=[o.pk for o in objs]).delete()
        except ProtectedError as error:
            blockers = sorted({str(o._meta.verbose_name_plural) for o in error.protected_objects})
            messages.error(request, f"Nothing was deleted: some of these are still used by {', '.join(blockers)}. "
                                    "Remove those first, or delete the items one at a time to see which.")
            return redirect(back)
        noun = _singular(screen) if count == 1 else _title(screen).lower()
        messages.success(request, f"{count} {noun} deleted.")
        return redirect(back)

    collector = NestedObjects(using=router.db_for_write(model))
    collector.collect(objs)
    also = [
        {"name": str(related._meta.verbose_name_plural), "count": len(instances)}
        for related, instances in collector.model_objs.items() if related is not model
    ]
    return render(request, "manage/delete_many.html", _base_context(
        request, key, screen=screen, title=_title(screen), singular=_singular(screen),
        objs=objs, also=also, back=back,
    ))


# ---------------------------------------------------------------------------
# Logo & favicon: one page, not a list, because the site has only one of each
# ---------------------------------------------------------------------------

@staff_only
def branding(request):
    obj = SiteBranding.load()
    FormClass = build_form(SiteBranding, ["logo", "show_name_with_logo", "favicon"])
    form = FormClass(request.POST or None, request.FILES or None, instance=obj)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        _record(request, saved, CHANGE, "Changed in the control room")
        messages.success(request, "Logo & favicon saved. They show across the site straight away.")
        return redirect("manage:branding")

    # The preview comes from the saved row (the `branding` context
    # processor), not the form, so a rejected upload never shows as current.
    return render(request, "manage/branding.html", _base_context(request, "branding", form=form))


@staff_only
def analytics_view(request):
    """Money, sign-ups, growth and learning activity for a chosen period."""
    data = analytics.build(request.GET)
    return render(request, "manage/analytics.html", _base_context(request, "analytics", data=data))


@staff_only
def bulk_students(request):
    """Register a school's students from an Excel sheet and hand back their logins."""
    return _bulk_people(request, "student")


@staff_only
def lesson_slides(request, pk):
    """A lesson item's photo slideshow: upload many pictures at once,
    caption and order them (apps/manage/slides.py)."""
    from . import slides

    return slides.manage(request, pk)


@staff_only
def bulk_teachers(request):
    """Register a school's teachers from an Excel sheet and hand back their logins."""
    return _bulk_people(request, "teacher")


def _bulk_people(request, kind):
    from django.conf import settings as dj_settings
    from django.http import HttpResponse

    from apps.schools.models import School

    from . import bulk_students as bulk

    k = bulk.KINDS[kind]
    schools = School.objects.order_by("name")
    chosen = schools.filter(pk=request.GET.get("school") or request.POST.get("school") or 0).first()

    if request.GET.get("template") and chosen:
        response = HttpResponse(bulk.template_file(chosen, kind), content_type=bulk.XLSX)
        response["Content-Disposition"] = f'attachment; filename="{chosen.code}-{k["many"]}-template.xlsx"'
        return response

    context = {"schools": schools, "chosen": chosen, "levels": bulk.LEVELS, "max_rows": bulk.MAX_ROWS,
               "kind": kind, "k": k, "page_url": reverse(f"manage:bulk_{k['many']}")}
    if chosen:
        context["allowed"], context["have"] = bulk.room_for(chosen, kind)
    if request.method == "POST":
        upload = request.FILES.get("file")
        if chosen is None:
            messages.error(request, f"Choose the school the {k['many']} belong to.")
        elif not upload:
            messages.error(request, "Choose the filled-in Excel file to upload.")
        else:
            try:
                rows = bulk.read_rows(upload, kind)
            except ValueError as error:
                messages.error(request, str(error))
                rows = None
            if rows is not None:
                if not rows:
                    messages.error(request, f"There are no {k['many']} in that file.")
                else:
                    clean, problems = bulk.check(chosen, rows, kind)
                    if problems:
                        context.update(problems=problems, row_count=len(rows))
                    else:
                        made = bulk.create(chosen, clean, kind)
                        site = getattr(dj_settings, "SITE_URL", "") or request.build_absolute_uri("/").rstrip("/")
                        data_url, filename = bulk.logins_file(chosen, made, site, kind)
                        _record(request, chosen, CHANGE, f"{len(made)} {k['many']} added in bulk")
                        context.update(made=made, logins_url=data_url, logins_name=filename)
    return render(request, "manage/bulk_students.html", _base_context(request, f"bulk-{k['many']}", **context))


class _TrialHolder:
    """A school's or a learner's own free trial, handled the same way: the
    length, reason and when it was set live on the School (schools) or the
    Subscription (learners); the end date always on the Subscription."""

    def __init__(self, school=None, subscription=None):
        from apps.billing.models import Subscription

        self.school = school
        if school is not None:
            self.sub, _made = Subscription.objects.get_or_create(school=school)
            self.name, self.log_obj = school.name, school
        else:
            self.sub = subscription
            self.name = subscription.user.get_full_name() or subscription.user.email
            self.log_obj = subscription.user

    def _put(self, **values):
        target = self.school if self.school is not None else self.sub
        names = {"length": "trial_length", "unit": "trial_unit", "set_at": "trial_set_at", "reason": "trial_reason"} \
            if self.school is not None else \
            {"length": "custom_trial_length", "unit": "custom_trial_unit", "set_at": "custom_trial_set_at", "reason": "custom_trial_reason"}
        for key, value in values.items():
            setattr(target, names[key], value)
        target.save(update_fields=[names[k] for k in values] + (["updated_at"] if target is self.sub else []))

    def give(self, length, unit, reason, start=None):
        from apps.billing.access import add_trial

        now = timezone.now()
        self.sub.trial_ends_at = add_trial(start or now, length, unit)
        self.sub.save(update_fields=["trial_ends_at", "updated_at"])
        self._put(length=length, unit=unit, set_at=now, reason=reason)

    def extend(self, length, unit, reason):
        from apps.billing.access import add_trial

        now = timezone.now()
        base = max(self.sub.trial_ends_at or now, now)
        self.sub.trial_ends_at = add_trial(base, length, unit)
        self.sub.save(update_fields=["trial_ends_at", "updated_at"])
        self._put(reason=reason)

    def end_now(self):
        self.sub.trial_ends_at = timezone.now()
        self.sub.save(update_fields=["trial_ends_at", "updated_at"])

    def use_general(self, days):
        self.sub.trial_ends_at = self.sub.created_at + timedelta(days=days)
        self.sub.save(update_fields=["trial_ends_at", "updated_at"])
        self._put(length=None, set_at=None, reason="")

    def paid_note(self):
        paid = self.sub.paid_until and self.sub.paid_until > timezone.now()
        return " They also have paid time, so access runs to whichever ends later." if paid else ""

    def ends(self):
        return f"{timezone.localtime(self.sub.trial_ends_at):%d %b %Y}"


def _trial_holder(target):
    """"school:5" or "learner:12" (a subscription) from the edit forms."""
    from apps.billing.models import Subscription
    from apps.schools.models import School

    kind, _sep, pk = (target or "").partition(":")
    if kind == "school":
        school = School.objects.filter(pk=pk).first()
        return _TrialHolder(school=school) if school else None
    if kind == "learner":
        sub = Subscription.objects.filter(pk=pk, user__isnull=False).select_related("user").first()
        return _TrialHolder(subscription=sub) if sub else None
    return None


@staff_only
def billing_settings(request):
    from apps.billing.access import subscription_for, trial_label
    from apps.billing.models import Subscription
    from apps.schools.models import School

    obj = BillingSettings.load()
    FormClass = build_form(BillingSettings, ["paywall_enabled", "trial_days", "reminder_days", "support_email"])
    action = request.POST.get("action", "") if request.method == "POST" else ""
    form = FormClass(request.POST if action == "" and request.method == "POST" else None, instance=obj)
    trial_form = SchoolTrialForm(request.POST if action == "school_trial" else None)
    learner_form = LearnerTrialForm(request.POST if action == "learner_trial" else None)
    edit_target = request.POST.get("target", "") if action == "edit_trial" else ""
    edit_form = EditTrialForm(request.POST if action == "edit_trial" else None)

    def done(message):
        messages.success(request, message)
        return redirect("manage:billing_settings")

    if action == "school_trial" and trial_form.is_valid():
        d = trial_form.cleaned_data
        holder = _TrialHolder(school=d["school"])
        holder.give(d["length"], d["unit"], d["reason"])
        _record(request, holder.log_obj, CHANGE, f"Own free trial set: {trial_label(d['length'], d['unit'])} ({d['reason']})")
        return done(f"{holder.name} now has a {trial_label(d['length'], d['unit'])} free trial, until {holder.ends()}.{holder.paid_note()}")

    if action == "learner_trial" and learner_form.is_valid():
        d = learner_form.cleaned_data
        holder = _TrialHolder(subscription=subscription_for(d["learner"]))
        holder.give(d["length"], d["unit"], d["reason"])
        _record(request, holder.log_obj, CHANGE, f"Own free trial set: {trial_label(d['length'], d['unit'])} ({d['reason']})")
        return done(f"{holder.name} now has a {trial_label(d['length'], d['unit'])} free trial, until {holder.ends()}.{holder.paid_note()}")

    if action == "edit_trial" and edit_form.is_valid():
        holder = _trial_holder(edit_target)
        if holder is None:
            return redirect("manage:billing_settings")
        d = edit_form.cleaned_data
        if d["length"] and d["mode"] == "restart":
            holder.give(d["length"], d["unit"], d["reason"])
            note = f"a new {trial_label(d['length'], d['unit'])} trial from today"
        elif d["length"]:
            holder.extend(d["length"], d["unit"], d["reason"])
            note = f"{trial_label(d['length'], d['unit'])} more"
        else:
            holder._put(reason=d["reason"])
            note = "a new reason"
        _record(request, holder.log_obj, CHANGE, f"Own free trial changed: {note} ({d['reason']})")
        return done(f"{holder.name}: {note}. Their trial ends {holder.ends()}.{holder.paid_note() if d['length'] else ''}")

    if action == "end_trial":
        holder = _trial_holder(request.POST.get("target"))
        if holder is not None:
            holder.end_now()
            _record(request, holder.log_obj, CHANGE, "Own free trial ended")
            return done(f"{holder.name}'s free trial has ended." + (" Their paid time carries on." if holder.paid_note() else ""))
        return redirect("manage:billing_settings")

    if action in ("clear_school_trial", "clear_learner_trial"):
        target = f"school:{request.POST.get('school')}" if action == "clear_school_trial" else f"learner:{request.POST.get('subscription')}"
        holder = _trial_holder(target)
        if holder is not None:
            holder.use_general(obj.trial_days)
            _record(request, holder.log_obj, CHANGE, "Own free trial removed")
            return done(f"{holder.name} is back on the general {obj.trial_days}-day trial.")
        return redirect("manage:billing_settings")

    if request.method == "POST" and action == "" and form.is_valid():
        saved = form.save()
        _record(request, saved, CHANGE, "Changed in the control room")
        return done("Billing settings saved.")

    def row(target, label, reason, sub, set_at):
        return {
            "target": target, "label": label, "reason": reason, "set_at": set_at,
            "ends": sub.trial_ends_at if sub else None, "state": sub.state() if sub else "none",
            "form": edit_form if edit_target == target else EditTrialForm(initial={"reason": reason, "mode": "add", "unit": "days"}, prefix=None),
            "open": edit_target == target,
        }

    custom = []
    for school in School.objects.filter(trial_length__isnull=False).select_related("subscription").order_by("name"):
        r = row(f"school:{school.pk}", school.custom_trial_label, school.trial_reason,
                getattr(school, "subscription", None), school.trial_set_at)
        r["school"] = school
        custom.append(r)
    learner_trials = []
    for sub in Subscription.objects.filter(user__isnull=False, custom_trial_length__isnull=False) \
            .select_related("user").order_by("user__first_name", "user__email"):
        r = row(f"learner:{sub.pk}", trial_label(sub.custom_trial_length, sub.custom_trial_unit),
                sub.custom_trial_reason, sub, sub.custom_trial_set_at)
        r["sub"] = sub
        learner_trials.append(r)

    return render(request, "manage/billing_settings.html", _base_context(
        request, "billing-settings", form=form, trial_form=trial_form, custom_trials=custom,
        learner_form=learner_form, learner_trials=learner_trials,
        paystack_ready=paystack.is_configured(), paystack_live=paystack.is_live(),
        webhook_url=request.build_absolute_uri(reverse("billing:webhook")),
    ))


@staff_only
def read_along(request):
    """Every recording that has a read-along, and how well it matches the
    words beside it."""
    rows = []
    for timing in ReadAlongTiming.objects.select_related("content_type").order_by("quality", "-updated_at"):
        obj = timing.content_object
        rows.append({
            "timing": timing,
            "object": obj,
            "recording": book_read_along.recording_name(obj) if obj is not None else "",
            "matches": timing.matches_text,
            "can_fix": obj is not None and book_read_along.can_replace_text(obj),
        })
    # Why the words didn't come back, most common first, in plain words.
    from collections import Counter

    errors = Counter(row["timing"].error for row in rows if row["timing"].error)
    problem = errors.most_common(1)[0] if errors else None
    if request.method == "POST" and request.POST.get("action") == "retry_failed":
        queued = 0
        for row in rows:
            if row["object"] is not None and (book_read_along.needs_retry(row["timing"])
                                              or row["timing"].status == ReadAlongTiming.STATUS_FAILED):
                book_read_along.measure_in_background(row["object"])
                queued += 1
        messages.success(request, f"Measuring {queued} recording{'s' if queued != 1 else ''} again in the background. "
                                  "Refresh this page in a few minutes to see the results.")
        return redirect("manage:read_along")
    return render(request, "manage/read_along.html", _base_context(
        request, "read-along", rows=rows,
        poor=sum(1 for row in rows if not row["matches"]),
        configured=book_read_along.is_configured(),
        problem=problem and {"error": problem[0], "count": problem[1], "advice": book_read_along.explain(problem[0])},
        without_words=sum(1 for row in rows if book_read_along.needs_retry(row["timing"])),
    ))


@staff_only
def read_along_detail(request, pk):
    """One recording: what the page says, what the voice says, and the two
    ways to bring them together."""
    timing = get_object_or_404(ReadAlongTiming.objects.select_related("content_type"), pk=pk)
    obj = timing.content_object
    if obj is None:
        timing.delete()
        messages.info(request, "That lesson has been deleted, so its timing has been tidied away.")
        return redirect("manage:read_along")

    said = book_read_along.spoken_text(timing.words)
    can_fix = book_read_along.can_replace_text(obj)

    if request.method == "POST":
        if request.POST.get("action") == "save_taps" and book_read_along.can_tap_along(obj):
            try:
                starts = json.loads(request.POST.get("taps") or "[]")
                book_read_along.save_tapped(obj, starts)
            except (ValueError, TypeError) as error:
                messages.error(request, f"Those taps couldn't be saved: {error} Please tap along again.")
            else:
                _record(request, obj, CHANGE, "Read-along timed by hand (Tap along)")
                messages.success(request, "Saved. The highlight now follows your taps exactly. "
                                          "Open the card and press play to check it.")
            return redirect("manage:read_along_detail", pk=timing.pk)
        if request.POST.get("action") == "remeasure" and timing.engine == book_read_along.MANUAL:
            # Let go of the hand-set timing and measure automatically again.
            timing.delete()
            book_read_along.measure_in_background(obj)
            messages.success(request, "Your tapped timing was cleared; measuring automatically again. Refresh in a minute.")
            return redirect("manage:read_along")
        if request.POST.get("action") == "trim" and can_fix:
            removed = book_read_along.trim_to_spoken(obj, timing)
            if removed:
                _record(request, obj, CHANGE, f"Trimmed {removed} unread words from the text")
                messages.success(
                    request,
                    f"Removed the {removed} word{'s' if removed != 1 else ''} the recording never reads. "
                    "The rest of your text is unchanged, and the highlight now follows all of it.",
                )
            else:
                messages.info(request, "Nothing to trim — the recording reads the whole text.")
            return redirect("manage:read_along_detail", pk=timing.pk)
        if request.POST.get("action") == "use_spoken" and can_fix and said:
            book_read_along.replace_text_with_spoken(obj, timing)
            _record(request, obj, CHANGE, "Text replaced with the recording's own words")
            messages.success(
                request,
                f"The page now says exactly what the recording says, so the highlight follows it word for word. "
                f"Open {_singular_for(obj).lower()} and press play to see it.",
            )
        else:
            book_read_along.measure_in_background(obj)
            messages.success(request, "Measuring this recording again. Refresh in a moment.")
        return redirect("manage:read_along_detail", pk=timing.pk)

    page_text = book_read_along.text_for(obj)
    tap = None
    if book_read_along.can_tap_along(obj):
        items = book_read_along.tap_items(obj)
        # Where each item starts now, to show beside it (tapped or measured).
        starts = []
        if timing.engine == book_read_along.MANUAL:
            at = 0
            for item in items:
                starts.append(timing.words[at][1] if at < len(timing.words) else None)
                at += len(item.split())
        tap = {"items": items, "src": book_read_along.media_url(obj), "starts": starts,
               "manual": timing.engine == book_read_along.MANUAL}
    return render(request, "manage/read_along.html", _base_context(
        request, "read-along", timing=timing, object=obj, said=said, can_fix=can_fix,
        page_text=page_text, detail=True, cover=book_read_along.coverage(page_text, timing.words),
        configured=book_read_along.is_configured(), tap=tap,
        recording=book_read_along.recording_name(obj),
    ))


def _singular_for(obj):
    return str(obj._meta.verbose_name).capitalize()


# ---------------------------------------------------------------------------
# The one-press jobs
# ---------------------------------------------------------------------------

@staff_only
@require_POST
def run_job(request, job):
    if job == "word-audio":
        started = jobs.start_word_audio()
        note = "Generating pronunciation for words that have none."
    elif job == "chart-audio":
        started = jobs.start_chart_audio()
        note = "Generating the missing phonemic chart recordings."
    elif job == "video-posters":
        started = jobs.start_video_posters()
        note = "Taking thumbnails from the videos."
    else:
        raise Http404("No such job.")

    if started:
        messages.success(request, f"{note} Refresh in a minute to see progress.")
    else:
        messages.info(request, "Nothing to start: it is already done, a run is going, or the service isn't set up.")
    return redirect("manage:home")


# ---------------------------------------------------------------------------
# Bringing in a level of the Echospell book
# ---------------------------------------------------------------------------

# One book at a time: parsed levels are held in the session between the
# preview and saving, and a whole series would be too much to keep there.
IMPORT_LIMIT = 600_000
SESSION_KEY = "echospell-import"


@staff_only
def echospell_import(request):
    """Upload a level of the Echospell book and let its groups fill in
    their own cards: the words, the passage and the conversation.

    Nothing is saved until the preview has been agreed to, and nothing is
    ever deleted — a card that already has words keeps them unless the
    admin asks for the text to be rewritten."""
    levels = list(Level.objects.all())
    mode = request.POST.get("mode") or echospell_importer.FILL_GAPS
    context = {"levels": levels, "mode": mode}

    if request.method != "POST":
        request.session.pop(SESSION_KEY, None)
        return render(request, "manage/echospell_import.html", _base_context(request, "echospell-import", **context))

    if request.POST.get("step") == "save":
        found = request.session.get(SESSION_KEY)
        if not found:
            messages.error(request, "That upload has expired. Please choose the file again.")
            return redirect("manage:echospell_import")
        level = _import_level(request, found)
        if level is None:
            return redirect("manage:echospell_import")
        report = echospell_importer.apply_import(found, level, mode)
        request.session.pop(SESSION_KEY, None)
        for done in report["groups"]:
            group = Group.objects.filter(level=level, number=done["number"]).first()
            if group and done["did"]:
                _record(request, group, ADDITION if done["group_created"] else CHANGE,
                        "From the Echospell book: " + ", ".join(done["did"]))
        messages.success(
            request,
            f"{report['created']} card{'s' if report['created'] != 1 else ''} added"
            + (f", {report['updated']} rewritten" if report["updated"] else "")
            + f" in {level.name}."
        )
        return render(request, "manage/echospell_import.html", _base_context(
            request, "echospell-import", report=report, level=level, **context))

    upload = request.FILES.get("book")
    if upload is None:
        messages.error(request, "Choose the book file first.")
        return redirect("manage:echospell_import")

    try:
        found = echospell_importer.parse(echospell_importer.read_text(upload))
    except echospell_importer.CannotRead as error:
        messages.error(request, str(error))
        return redirect("manage:echospell_import")

    if len(json.dumps(found)) > IMPORT_LIMIT:
        messages.error(request, "That file holds more than one level. Please upload one level at a time.")
        return redirect("manage:echospell_import")

    request.session[SESSION_KEY] = found
    level = _import_level(request, found, quiet=True)
    plan = echospell_importer.describe_plan(found, level, mode) if level else {"plan": found["groups"], "missing_types": []}
    return render(request, "manage/echospell_import.html", _base_context(
        request, "echospell-import", found=found, plan=plan, level=level,
        level_missing=level is None, file_name=upload.name, **context))


def _import_level(request, found, quiet=False):
    """The level this book belongs to: the one chosen, or the one named in
    the book itself, made if it isn't there yet."""
    chosen = request.POST.get("level")
    if chosen and chosen.isdigit():
        return Level.objects.filter(pk=int(chosen)).first()
    name = found.get("level") or ""
    if not name:
        if not quiet:
            messages.error(request, "The book names more than one level. Choose which one to fill in.")
        return None
    level = echospell_importer.level_for(name, create=bool(request.POST.get("create_level")))
    if level is None and not quiet:
        messages.error(request, f"There is no {name} yet. Tick “create it” or choose another level.")
    return level


# ---------------------------------------------------------------------------
# Results & marking: every attempt, and grading what a person has to judge
# ---------------------------------------------------------------------------

@staff_only
def results_list(request):
    show = "to-mark" if request.GET.get("show") == "to-mark" else "all"
    source = request.GET.get("from") if request.GET.get("from") in results.SOURCES else None
    query = request.GET.get("q", "").strip()
    found = results.rows(show=show, source=source, query=query)
    page = Paginator(found, PER_PAGE).get_page(request.GET.get("page"))
    return render(request, "manage/results.html", _base_context(
        request, "results", page=page, show=show, source=source, query=query,
        sources=[{"key": key, **spec} for key, spec in results.SOURCES.items()], total=len(found),
    ))


@staff_only
def result_detail(request, source, pk):
    attempt = results.get_attempt(source, pk)
    if attempt is None:
        raise Http404("No such attempt.")
    errors = []

    if request.method == "POST":
        if source == "assessment":
            errors = results.mark_assessment(attempt, request.user, request.POST)
        else:
            marks = {}
            for response in attempt.responses.all():
                choice = request.POST.get(f"verdict-{response.pk}", "")
                if choice.isdecimal() and 0 <= int(choice) <= 5:
                    marks[response.pk] = int(choice)
                elif choice in ("good", "work"):
                    # Accept forms already open when this control was updated.
                    marks[response.pk] = 5 if choice == "good" else 0
            if results.mark_activity(attempt, marks, request.POST.get("feedback", "")):
                errors = ["Mark every recording by choosing a score from 0 to 5."]
        if not errors:
            audio_feedback = request.FILES.get("teacher_audio_feedback")
            if audio_feedback:
                if attempt.teacher_audio_feedback:
                    attempt.teacher_audio_feedback.delete(save=False)
                attempt.teacher_audio_feedback = audio_feedback
                attempt.save(update_fields=["teacher_audio_feedback"])
            _record(request, attempt, CHANGE, "Marked in the control room")
            messages.success(request, f"Marks saved. {results.learner_name(attempt.user)} can see them on their result.")
            nxt = results.rows(show="to-mark")
            if nxt:
                return redirect("manage:result", source=nxt[0]["source"], pk=nxt[0]["pk"])
            return redirect(f"{reverse('manage:results')}?show=to-mark")

    context = {"source": source, "spec": results.SOURCES[source], "attempt": attempt,
               "row": results.summarise(source, attempt), "errors": errors, "posted": request.POST}
    if source == "assessment":
        context.update(answers=results.assessment_answers(attempt), scale=["1", "2", "3", "4", "5"],
                       can_mark=attempt.status != attempt.Status.IN_PROGRESS
                       and any(not a.question.is_objective for a in attempt.answers.select_related("question")))
    else:
        answers = results.activity_answers(attempt, request.POST)
        context.update(answers=answers, can_mark=any(a["is_recording"] for a in answers),
                       recording_marks=results.RECORDING_MARKS)
    return render(request, "manage/result_detail.html", _base_context(request, "results", **context))


# ---------------------------------------------------------------------------
# Schools & people
# ---------------------------------------------------------------------------

@staff_only
def schools_directory(request):
    """Every school at a glance: plan, people and limits."""
    from . import school_directory

    return render(request, "manage/schools_directory.html",
                  _base_context(request, "schools-directory", **school_directory.directory(request)))


@staff_only
def bulk_schools(request):
    """Register schools and generate first-login credentials from Excel."""
    from io import BytesIO

    from django.http import FileResponse

    from apps.accounts.models import INTERNAL_EMAIL_DOMAIN, User
    from apps.schools.models import School

    from . import bulk_schools as school_import

    if request.method == "GET" and request.GET.get("template") == "1":
        response = FileResponse(
            BytesIO(school_import.template_file()),
            as_attachment=True,
            filename="school-registration-template.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    form = school_import.SchoolWorkbookForm(request.POST or None, request.FILES or None)
    row_errors = []
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["workbook"]
        try:
            records, row_errors = school_import.parse_workbook(upload)
        except school_import.SchoolWorkbookError as error:
            form.add_error("workbook", str(error))
        else:
            if not row_errors:
                existing = {
                    school_import.normalize_school_name(name)
                    for name in School.objects.values_list("name", flat=True)
                }
                new_records = [
                    record for record in records
                    if school_import.normalize_school_name(record["name"]) not in existing
                ]
                skipped = len(records) - len(new_records)
                if not new_records:
                    messages.info(request, f"No new schools needed registration; {skipped} existing school{'s' if skipped != 1 else ''} were skipped without changes.")
                    return redirect("manage:schools_directory")

                reserved_usernames = {
                    username.casefold()
                    for username in User.objects.exclude(username__isnull=True).values_list("username", flat=True)
                    if username
                }
                reserved_emails = {
                    email.casefold()
                    for email in User.objects.filter(email__iendswith=f"@{INTERNAL_EMAIL_DOMAIN}")
                    .values_list("email", flat=True)
                }
                reserved_codes = set(School.objects.values_list("code", flat=True))

                credentials = []
                school_objects = []
                for record in new_records:
                    login = school_import.new_school_admin_login(
                        record["contact_person"], record["name"], reserved_usernames, reserved_emails,
                    )
                    school = School(
                        code=school_import.new_school_code(reserved_codes),
                        name=record["name"],
                        address=record["address"],
                        contact_person=record["contact_person"],
                        phone=record["phone"],
                        email=record["email"],
                        relationship_status=record["relationship_status"],
                    )
                    school_objects.append(school)
                    credentials.append({**login, "school": school})

                password_hashes = school_import.hash_school_admin_passwords(credentials)
                credential_workbook = school_import.credentials_file(credentials)
                try:
                    with transaction.atomic():
                        School.objects.bulk_create(school_objects, batch_size=100)
                        schools_by_code = School.objects.in_bulk(
                            [school.code for school in school_objects], field_name="code",
                        )
                        if len(schools_by_code) != len(school_objects):
                            raise IntegrityError("A school record could not be read back after bulk registration.")

                        from apps.accounts.credentials import encrypt_login_password

                        users = [
                            User(
                                email=account["email"],
                                username=account["username"],
                                password=password_hash,
                                first_name=account["first_name"],
                                last_name=account["last_name"],
                                role=User.Role.SCHOOL_ADMIN,
                                school=schools_by_code[account["school"].code],
                                encrypted_login_password=encrypt_login_password(account["password"]),
                            )
                            for account, password_hash in zip(credentials, password_hashes)
                        ]
                        User.objects.bulk_create(users, batch_size=100)

                        school_content_type = ContentType.objects.get_for_model(School)
                        LogEntry.objects.bulk_create([
                            LogEntry(
                                user_id=request.user.pk,
                                content_type_id=school_content_type.pk,
                                object_id=str(schools_by_code[school.code].pk),
                                object_repr=str(school)[:200],
                                action_flag=ADDITION,
                                change_message="Registered from Excel with generated school admin login",
                            )
                            for school in school_objects
                        ], batch_size=100)
                except IntegrityError:
                    messages.error(request, "A database conflict stopped the import. No schools or admin accounts were saved; review the file and try again.")
                else:
                    note = f"Registered {len(new_records)} schools with new admin logins. The Excel credential sheet is downloading."
                    if skipped:
                        note += f" Skipped {skipped} schools already in the system."
                    messages.success(request, note)
                    stamp = timezone.localdate().strftime("%Y%m%d")
                    response = FileResponse(
                        BytesIO(credential_workbook),
                        as_attachment=True,
                        filename=f"school-login-details-{stamp}.xlsx",
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    response["Cache-Control"] = "private, no-store"
                    response["X-Content-Type-Options"] = "nosniff"
                    return response

    return render(request, "manage/bulk_schools.html", _base_context(
        request,
        "schools-directory",
        form=form,
        row_errors=row_errors,
        max_schools=school_import.MAX_SCHOOLS,
    ))


@staff_only
def school_people(request, pk):
    """One school's teachers, students and admins, with their details."""
    from django.http import HttpResponse

    from . import school_directory

    result = school_directory.people(request, pk)
    if isinstance(result, HttpResponse):
        return result
    return render(request, "manage/school_people.html", _base_context(request, "schools-directory", **result))


@staff_only
@require_POST
def school_login_sheet(request, pk):
    """Download saved current passwords for active school members, without changing them."""
    from django.conf import settings as dj_settings
    from django.http import HttpResponse

    from apps.accounts.models import User
    from apps.accounts.credentials import decrypt_login_password
    from apps.schools.models import School

    from . import bulk_students as bulk

    school = get_object_or_404(School, pk=pk)
    members = list(
        User.objects.filter(
            school=school,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        ).order_by("role", "first_name", "last_name", "pk")
    )
    if not members:
        messages.warning(request, "This school has no active accounts to include in a login sheet.")
        return redirect("manage:school_people", pk=school.pk)

    accounts = []
    for member in members:
        password = decrypt_login_password(member.encrypted_login_password)
        accounts.append({
            "user": member,
            "password": password if password is not None else "Unavailable — old password or recovery key unavailable",
            "password_available": password is not None,
        })

    site_url = (getattr(dj_settings, "SITE_URL", "") or request.build_absolute_uri("/")).rstrip("/")
    content, filename = bulk.school_logins_file(school, accounts, site_url)
    _record(request, school, CHANGE, f"Downloaded current login sheet for {len(members)} active school accounts")

    response = HttpResponse(content, content_type=bulk.XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response
