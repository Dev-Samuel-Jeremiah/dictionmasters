"""
Everything the admin console shows: headline numbers, what needs doing,
the content library with add and manage links, and recent changes.

Links only appear for what the signed-in admin is allowed to do, using
each ModelAdmin's own permission checks, so a limited staff account sees
a smaller console rather than buttons that lead to "permission denied".
"""

from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.assessments.models import Assessment, Attempt
from apps.book import phoneme_audio, video_poster
from apps.clash.models import Match
from apps.echospell.models import Activity, ActivityAttempt
from apps.quick_words.models import QuickWord
from apps.quick_words.speech import is_configured as speech_configured
from apps.schools.models import School

from . import jobs
from .features import FEATURES, QUICK_ADDS


def _model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def _screen(request, label):
    """Name, count and links for one admin screen, or None if the admin
    can't see it."""
    model = _model(label)
    model_admin = admin.site._registry.get(model) if model else None
    if model_admin is None or not model_admin.has_view_or_change_permission(request):
        return None
    info = (model._meta.app_label, model._meta.model_name)
    try:
        changelist = reverse("admin:%s_%s_changelist" % info)
    except NoReverseMatch:
        return None
    add = None
    if model_admin.has_add_permission(request):
        try:
            add = reverse("admin:%s_%s_add" % info)
        except NoReverseMatch:
            add = None
    return {
        "name": str(model._meta.verbose_name_plural).capitalize(),
        "singular": str(model._meta.verbose_name),
        "count": model._default_manager.count(),
        "changelist": changelist,
        "add": add,
    }


def _features(request):
    rows = []
    for feature in FEATURES:
        screens = [s for s in (_screen(request, label) for label in feature["models"]) if s]
        if not screens:
            continue
        site = None
        if feature["site_url"]:
            try:
                site = reverse(feature["site_url"])
            except NoReverseMatch:
                site = None
        rows.append({**feature, "screens": screens, "site": site})
    return rows


def _quick_adds(request):
    buttons = []
    for label, name, icon in QUICK_ADDS:
        screen = _screen(request, label)
        if screen and screen["add"]:
            buttons.append({"name": name, "icon": icon, "url": screen["add"]})
    return buttons


def _admin_link(label, query=""):
    model = _model(label)
    if not model:
        return None
    try:
        return reverse("admin:%s_%s_changelist" % (model._meta.app_label, model._meta.model_name)) + query
    except NoReverseMatch:
        return None


def _attention():
    """Things waiting on an admin, most urgent first. Only items with
    something to do are returned."""
    items = []

    speaking = Attempt.objects.filter(status=Attempt.Status.AWAITING).count()
    if speaking:
        items.append({
            "tone": "bad", "icon": "🎤", "count": speaking,
            "title": f"{speaking} speaking assessment{'s' if speaking != 1 else ''} to mark",
            "text": "Learners are waiting for their result.",
            "link": reverse("assessments:marking_queue"), "link_label": "Open marking",
        })

    recordings = ActivityAttempt.objects.filter(status=ActivityAttempt.STATUS_AWAITING).count()
    if recordings:
        items.append({
            "tone": "bad", "icon": "🎙️", "count": recordings,
            "title": f"{recordings} EchoSpell recording{'s' if recordings != 1 else ''} to review",
            "text": "Read-aloud activities sent to a teacher.",
            "link": _admin_link("echospell.activityattempt", "?status__exact=awaiting"), "link_label": "Review",
        })

    no_audio = jobs.words_without_audio().count()
    if no_audio:
        items.append({
            "tone": "wait", "icon": "🔇", "count": no_audio,
            "title": f"{no_audio} Quick Word{'s' if no_audio != 1 else ''} without audio",
            "text": "Generating now…" if jobs.word_audio_running() else "Generate their pronunciation with ElevenLabs.",
            "action": "console:generate_word_audio" if speech_configured() and not jobs.word_audio_running() else None,
            "action_label": "Generate audio",
            "link": _admin_link("quick_words.quickword"), "link_label": "View words",
        })

    chart_missing = len(phoneme_audio.missing_entries())
    if chart_missing:
        items.append({
            "tone": "wait", "icon": "🔤", "count": chart_missing,
            "title": f"{chart_missing} phonemic chart sound{'s' if chart_missing != 1 else ''} without audio",
            "text": "Made automatically when the chart is opened, or generate them all now.",
            "action": "console:generate_chart_audio" if speech_configured() else None,
            "action_label": "Generate audio",
            "link": _admin_link("book.phonemeaudio"), "link_label": "View recordings",
        })

    no_poster = jobs.videos_without_posters()
    if no_poster:
        items.append({
            "tone": "wait", "icon": "🎬", "count": no_poster,
            "title": f"{no_poster} video{'s' if no_poster != 1 else ''} without a thumbnail",
            "text": "Made from the video itself so it doesn't open on a black screen."
                    if video_poster.thumbnails_available()
                    else "ffmpeg isn't installed on this server, so thumbnails can't be made.",
            "action": "console:generate_video_posters" if video_poster.thumbnails_available() else None,
            "action_label": "Make thumbnails",
            "link": None, "link_label": "",
        })

    drafts = Activity.objects.filter(is_published=False).count() + Assessment.objects.filter(is_published=False).count()
    if drafts:
        items.append({
            "tone": "info", "icon": "📝", "count": drafts,
            "title": f"{drafts} unpublished activit{'ies' if drafts != 1 else 'y'} and assessment{'s' if drafts != 1 else ''}",
            "text": "Hidden from learners until published.",
            "link": _admin_link("echospell.activity", "?is_published__exact=0"), "link_label": "See drafts",
        })
    return items


def _recent_changes():
    rows = []
    for entry in LogEntry.objects.select_related("user", "content_type")[:12]:
        rows.append({
            "when": entry.action_time,
            "who": entry.user.get_full_name() or entry.user.email,
            "action": {1: "Added", 2: "Changed", 3: "Deleted"}.get(entry.action_flag, "Changed"),
            "flag": entry.action_flag,
            "what": entry.object_repr,
            "type": entry.content_type.name if entry.content_type else "",
            "url": entry.get_admin_url() if entry.action_flag != 3 else "",
        })
    return rows


def console_context(request):
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    learners = User.objects.filter(role__in=[User.Role.STUDENT, User.Role.INDIVIDUAL])
    words = QuickWord.objects.filter(is_published=True)
    words_total = words.count()
    words_audio = words_total - jobs.words_without_audio().count()
    chart_total = len(phoneme_audio.chart_entries())
    chart_done = chart_total - len(phoneme_audio.missing_entries())

    hour = timezone.localtime(now).hour
    return {
        "console": {
            "greeting": "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening",
            "stats": [
                {"label": "Learners", "value": learners.count(), "note": f"+{learners.filter(date_joined__gte=week_ago).count()} this week", "icon": "🧑‍🎓", "link": _admin_link("accounts.user")},
                {"label": "Schools", "value": School.objects.count(), "note": f"{User.objects.filter(role=User.Role.TEACHER).count()} teachers", "icon": "🏫", "link": _admin_link("schools.school")},
                {"label": "Quick Words", "value": words_total, "note": f"{words_audio} with audio", "icon": "🔤", "link": _admin_link("quick_words.quickword")},
                {"label": "Chart audio", "value": f"{chart_done}/{chart_total}", "note": "phonemic chart sounds", "icon": "🔊", "link": _admin_link("book.phonemeaudio")},
                {"label": "To mark", "value": Attempt.objects.filter(status=Attempt.Status.AWAITING).count() + ActivityAttempt.objects.filter(status=ActivityAttempt.STATUS_AWAITING).count(), "note": "speaking & recordings", "icon": "✍️", "link": reverse("assessments:marking_queue")},
                {"label": "Clash games", "value": Match.objects.filter(started_at__gte=week_ago).count(), "note": "in the last 7 days", "icon": "⚔️", "link": _admin_link("clash.match")},
            ],
            "quick_adds": _quick_adds(request),
            "attention": _attention(),
            "features": _features(request),
            "recent": _recent_changes(),
            "services": [
                {"name": "Cloudflare R2 media storage", "ok": settings.R2_CONFIGURED, "ok_text": "Connected: uploads go to R2", "bad_text": "Not configured: uploads stay on this server"},
                {"name": "ElevenLabs pronunciation", "ok": speech_configured(), "ok_text": "Ready", "bad_text": "Add ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID"},
                {"name": "Groq word look-up", "ok": bool(getattr(settings, "GROQ_API_KEY", "")), "ok_text": "Ready", "bad_text": "Add GROQ_API_KEY"},
                {"name": "Paystack payments", "ok": bool(getattr(settings, "PAYSTACK_SECRET_KEY", "")), "ok_text": "Live: taking real payments" if getattr(settings, "PAYSTACK_SECRET_KEY", "").startswith("sk_live_") else "Test mode: no real money moves", "bad_text": "Add PAYSTACK_SECRET_KEY"},
            ],
        }
    }
