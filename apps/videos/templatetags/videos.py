"""
`{% video_player entry %}
{% load videos %}` — a lesson video, ready to play and, for a
learner, ready to keep for later.

The address it plays from is a ticket for this signed-in person that
lasts minutes (apps/videos/links.py), so nothing in the page points at
where the video really lives.
"""

from django import template

from django.contrib.contenttypes.models import ContentType

from ..links import ticket, watch_url

register = template.Library()


@register.inclusion_tag("videos/_player.html", takes_context=True)
def video_player(context, entry, poster=None, offline=True, ra=False):
    request = context.get("request")
    user = getattr(request, "user", None)
    if entry is None or not getattr(entry, "video_source", ""):
        return {"missing": True}

    stored = bool(getattr(entry, "video_file", None))
    signed_in = bool(user and user.is_authenticated)
    return {
        "missing": False,
        # A file of ours is served through Django; a video somewhere else
        # (YouTube, a CDN) keeps its own address.
        "src": watch_url(entry, user) if (stored and signed_in) else entry.video_source,
        "poster": poster if poster is not None else getattr(entry, "poster_source", ""),
        "caption": getattr(entry, "video_caption", ""),
        # Only our own files can be kept for offline viewing.
        "ticket": ticket(entry, user) if (stored and signed_in and offline) else "",
        # What the browser files its copy under: the lesson row it belongs to.
        "ref": f"{ContentType.objects.get_for_model(entry).pk}-{entry.pk}",
        "title": getattr(entry, "video_caption", "") or "Lesson video",
        # This video is the recording the page reads along with.
        "ra": ra,
    }
