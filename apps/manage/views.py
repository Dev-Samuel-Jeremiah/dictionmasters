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
from django.db.models import Q
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
from apps.landing.models import SiteBranding

from .forms import ControlLoginForm, build_form
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
    if hasattr(value, "url") and hasattr(value, "name"):      # a file or image
        return {"kind": "file", "text": value.name.rsplit("/", 1)[-1] if value else "", "url": value.url if value else ""}
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
    ))


@staff_only
def record_form(request, key, pk=None):
    screen = _screen_or_404(key)
    model = _model_for(screen)
    if screen.get("readonly"):
        messages.info(request, f"{_title(screen)} are written by the site itself, so they can only be viewed.")
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
    # Dropdowns offer only what belongs here, e.g. a trick's group is a trick group.
    for name, condition in screen.get("limit", {}).items():
        if name in form.fields and hasattr(form.fields[name], "queryset"):
            form.fields[name].queryset = form.fields[name].queryset.filter(**condition)

    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if parent_field and parent_obj and not pk:
            setattr(saved, parent_field, parent_obj)
        if not pk:
            for name, value in screen.get("defaults", {}).items():
                setattr(saved, name, value)
        saved.save()
        form.save_m2m()
        _record(request, saved, CHANGE if pk else ADDITION, "Changed in the control room" if pk else "Added in the control room")
        messages.success(request, f"{_singular(screen).capitalize()} “{saved}” {'updated' if pk else 'added'}.")
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
                "list_url": f"{reverse('manage:list', args=[child_key])}?in={obj.pk}",
            })

    return render(request, "manage/form.html", _base_context(
        request, key,
        screen=screen, form=form, obj=obj, title=_title(screen), singular=_singular(screen),
        parent_obj=parent_obj, children=children,
    ))


@staff_only
def record_delete(request, key, pk):
    screen = _screen_or_404(key)
    model = _model_for(screen)
    obj = get_object_or_404(_rows_for(screen), pk=pk)
    if screen.get("readonly"):
        messages.info(request, f"{_title(screen)} can only be viewed.")
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
    # Dropdowns offer only what belongs here, e.g. a trick's group is a trick group.
    for name, condition in screen.get("limit", {}).items():
        if name in form.fields and hasattr(form.fields[name], "queryset"):
            form.fields[name].queryset = form.fields[name].queryset.filter(**condition)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        _record(request, saved, CHANGE, "Changed in the control room")
        messages.success(request, "Logo & favicon saved. They show across the site straight away.")
        return redirect("manage:branding")

    # The preview comes from the saved row (the `branding` context
    # processor), not the form, so a rejected upload never shows as current.
    return render(request, "manage/branding.html", _base_context(request, "branding", form=form))


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
