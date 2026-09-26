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
from functools import wraps

from django.apps import apps as django_apps
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import transaction
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

from .forms import ControlLoginForm, QuickWordAudioZipForm, build_form
from . import analytics
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

    return render(request, "manage/list.html", _base_context(
        request, key,
        screen=screen, title=_title(screen), singular=_singular(screen),
        headings=headings, rows=table, page=page, query=query,
        parent_obj=parent_obj, parent_key=parent_key,
        readonly=screen.get("readonly", False), total=rows.count(),
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
                "bulk_url": f"{reverse('manage:bulk_questions', args=[child_key])}?in={obj.pk}"
                if child.get("bulk_add") else "",
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
def billing_settings(request):
    obj = BillingSettings.load()
    FormClass = build_form(BillingSettings, ["paywall_enabled", "trial_days", "reminder_days", "support_email"])
    form = FormClass(request.POST or None, instance=obj)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        _record(request, saved, CHANGE, "Changed in the control room")
        messages.success(request, "Billing settings saved.")
        return redirect("manage:billing_settings")

    return render(request, "manage/billing_settings.html", _base_context(
        request, "billing-settings", form=form,
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
            "matches": timing.matches_text,
            "can_fix": obj is not None and book_read_along.can_replace_text(obj),
        })
    return render(request, "manage/read_along.html", _base_context(
        request, "read-along", rows=rows,
        poor=sum(1 for row in rows if not row["matches"]),
        configured=book_read_along.is_configured(),
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
    return render(request, "manage/read_along.html", _base_context(
        request, "read-along", timing=timing, object=obj, said=said, can_fix=can_fix,
        page_text=page_text, detail=True, cover=book_read_along.coverage(page_text, timing.words),
        configured=book_read_along.is_configured(),
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
