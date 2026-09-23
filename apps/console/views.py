"""
Console pages that sit alongside the Django admin: one search box across
all content, and buttons that start the background audio jobs.
Everything here is for staff only.
"""

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.assessments.models import Assessment
from apps.book.models import PhonemeAudio, Sound
from apps.echospell.models import Activity, CardLesson, Level
from apps.learning_modules.models import LearningModule, LessonItem
from apps.quick_words.models import QuickWord
from apps.reading_club.models import Book, Chapter
from apps.reference_library.models import LibraryArticle
from apps.diction_library.models import LibraryItem
from apps.diction_radio.models import RadioProgram, RadioEpisode
from apps.schools.models import School

from . import jobs

RESULTS_PER_TYPE = 8

# (model, fields searched, how a result is described)
SEARCHES = [
    (QuickWord, ["word", "definition"], lambda o: o.definition),
    (User, ["email", "first_name", "last_name"], lambda o: f"{o.get_role_display()} · {o.email}"),
    (School, ["name", "email", "code"], lambda o: f"Code {o.code}"),
    (Sound, ["name", "symbol", "example_words"], lambda o: o.example_words),
    (PhonemeAudio, ["key", "symbol", "spoken_text"], lambda o: o.spoken_text),
    (Activity, ["title"], lambda o: f"{o.group.level.name} · Group {o.group.number} · {o.kind_label}"),
    (CardLesson, ["title", "words"], lambda o: f"{o.category} · {o.group}"),
    (Level, ["name", "description"], lambda o: o.age_range),
    (LearningModule, ["name", "description"], lambda o: o.description),
    (LessonItem, ["title", "description"], lambda o: str(o.day)),
    (Assessment, ["title", "summary"], lambda o: o.get_kind_display()),
    (Book, ["title", "author"], lambda o: o.author),
    (Chapter, ["title", "summary"], lambda o: str(o.term) if hasattr(o, "term") else ""),
    (LibraryArticle, ["title", "summary"], lambda o: o.category.name),
    (LibraryItem, ["title", "summary", "description"], lambda o: o.visibility_label),
    (RadioProgram, ["title", "tagline", "presenter", "description"], lambda o: f"{o.episodes.filter(is_published=True).count()} published episodes"),
    (RadioEpisode, ["title", "description", "program__title"], lambda o: o.program.title),
]


def _admin_url(obj):
    meta = obj._meta
    try:
        return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])
    except NoReverseMatch:
        return None


@staff_member_required
def search(request):
    query = request.GET.get("q", "").strip()
    groups = []
    if query:
        for model, fields, describe in SEARCHES:
            model_admin = admin.site._registry.get(model)
            if model_admin is None or not model_admin.has_view_or_change_permission(request):
                continue
            existing = [f for f in fields if any(field.name == f for field in model._meta.get_fields())]
            if not existing:
                continue
            condition = Q()
            for field in existing:
                condition |= Q(**{f"{field}__icontains": query})
            found = list(model._default_manager.filter(condition)[:RESULTS_PER_TYPE])
            if not found:
                continue
            results = []
            for obj in found:
                try:
                    detail = describe(obj) or ""
                except Exception:  # a missing relation shouldn't break the search page
                    detail = ""
                results.append({"label": str(obj), "detail": str(detail)[:140], "url": _admin_url(obj)})
            groups.append({"name": str(model._meta.verbose_name_plural).capitalize(), "results": results})

    context = {
        **admin.site.each_context(request),
        "title": f"Search: {query}" if query else "Search",
        "query": query,
        "groups": groups,
        "total": sum(len(g["results"]) for g in groups),
    }
    return TemplateResponse(request, "admin/console/search.html", context)


@staff_member_required
@require_POST
def generate_word_audio(request):
    if jobs.start_word_audio():
        messages.success(request, "Generating pronunciation audio for words that have none. Refresh in a minute or two to see progress.")
    else:
        messages.info(request, "Nothing to start: every word has audio, a run is already going, or ElevenLabs isn't set up.")
    return redirect("admin:index")


@staff_member_required
@require_POST
def generate_chart_audio(request):
    if jobs.start_chart_audio():
        messages.success(request, "Generating the missing phonemic chart recordings. They will appear within a minute.")
    else:
        messages.info(request, "Nothing to start: the chart is complete, a run is already going, or ElevenLabs isn't set up.")
    return redirect("admin:index")


@staff_member_required
@require_POST
def generate_video_posters(request):
    if jobs.start_video_posters():
        messages.success(request, "Taking thumbnails from the videos. They will appear within a minute or two.")
    else:
        messages.info(request, "Nothing to start: every video has a thumbnail, a run is already going, or ffmpeg isn't installed.")
    return redirect("admin:index")
