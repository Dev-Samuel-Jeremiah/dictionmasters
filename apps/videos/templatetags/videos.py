"""
`{% video_player entry %}
{% load videos %}` — a lesson video, ready to play and, for a
learner, ready to keep for later.

`{% audio_player entry %}` — a recording (the row's audio_file), playing
from its usual address as before, with the same "Save for offline" strip.

The address it plays from is a ticket for this signed-in person that
lasts minutes (apps/videos/links.py), so nothing in the page points at
where the video really lives.
"""

import re

from django import template

from django.contrib.contenttypes.models import ContentType

from ..links import AUDIO, MARKS, QUICK, VIDEO, stored_file, ticket, watch_url

register = template.Library()

HOOK = re.compile(r"data-[a-z][a-z-]*")


@register.inclusion_tag("videos/_player.html", takes_context=True)
def video_player(context, entry, poster=None, offline=True, ra=False, direct=False, title=""):
    """direct: play from the file's usual address, as a page did before it
    had this player (the Diction Library), rather than through a ticket
    that also checks the person's plan. Saving still checks it."""
    request = context.get("request")
    user = getattr(request, "user", None)
    stored = stored_file(entry, VIDEO) is not None
    source = getattr(entry, "video_source", "") or (_url_of(stored_file(entry, VIDEO)) if stored else "")
    if entry is None or not source:
        return {"missing": True}

    signed_in = bool(user and user.is_authenticated)
    return {
        "missing": False,
        # A file of ours is served through Django; a video somewhere else
        # (YouTube, a CDN) keeps its own address.
        "src": watch_url(entry, user) if (stored and signed_in and not direct) else source,
        "poster": poster if poster is not None else getattr(entry, "poster_source", ""),
        "caption": getattr(entry, "video_caption", ""),
        # Only our own files can be kept for offline viewing.
        "ticket": ticket(entry, user) if (stored and signed_in and offline) else "",
        # What the browser files its copy under: the lesson row it belongs to.
        "ref": f"{ContentType.objects.get_for_model(entry).pk}-{entry.pk}",
        "title": title or getattr(entry, "video_caption", "") or "Lesson video",
        # This video is the recording the page reads along with.
        "ra": ra,
    }


def _sync_url(obj):
    if obj is None or obj == "":
        return ""
    from apps.book import read_along

    return read_along.sync_url(obj) or ""


def _url_of(stored):
    try:
        return stored.url
    except ValueError:
        return ""


@register.inclusion_tag("videos/_audio.html", takes_context=True)
def audio_player(context, entry, title="", css="", ra=False, preload="none", dark=False, label="", hook="",
                 media=AUDIO, sync=None):
    """A recording with a "Save for offline" strip under it.

    css: classes for the <audio> itself; hook: one data- attribute a page's
    script finds it by (e.g. "data-recital-audio"); ra: it's the recording
    the page reads along with, and sync what its word timings belong to
    (book/templatetags/read_along.py); dark: it sits on a dark card;
    media="quick": an EchoSpell card's Quick recording, not its Full one.

    It plays from the address it always had (so nothing changes for
    listening online, or for the pages a level's app keeps by itself);
    only saving goes through a ticket. A recording somewhere else (an
    audio_url) plays as before, with nothing to save."""
    request = context.get("request")
    user = getattr(request, "user", None)
    media = QUICK if media == QUICK else AUDIO
    prefix = "quick_" if media == QUICK else ""
    stored = stored_file(entry, media)
    source = getattr(entry, f"{prefix}audio_source", "") if entry is not None else ""
    source = source or (_url_of(stored) if stored is not None else "")
    if not source:
        return {"missing": True}
    signed_in = bool(user and user.is_authenticated)
    keepable = stored is not None and signed_in and not getattr(entry, f"{prefix}audio_url", "")
    return {
        "missing": False,
        "src": source,
        "ticket": ticket(entry, user, media=media) if keepable else "",
        # What the browser files its copy under; "-a" (or "-q") keeps it
        # apart from the same row's video.
        "ref": f"{ContentType.objects.get_for_model(entry).pk}-{entry.pk}-{MARKS[media]}",
        "title": (title or getattr(entry, "title", "") or str(entry))[:200],
        "sync": _sync_url(sync),
        "css": css, "ra": ra, "preload": preload, "dark": dark, "label": label,
        "hook": hook if HOOK.fullmatch(hook or "") else "",
    }
