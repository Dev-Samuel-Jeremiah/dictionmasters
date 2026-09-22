"""
The address a lesson video is played from.

The browser never sees where a video really lives. It gets a link to
this site carrying a signed ticket that says which video, for which
signed-in person, and for how long. Django checks the ticket and the
person's access, then reads the bytes out of private R2 storage and
passes them on (see views.py).

A ticket copied out of the page is useless to anyone else: it is tied to
the account it was made for, and it stops working within minutes.
"""

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.urls import reverse

SALT = "dm.video.link"
WATCH = "watch"
KEEP = "keep"


def _ref(video):
    return ContentType.objects.get_for_model(video).pk, video.pk


def ticket(video, user, purpose=WATCH):
    """A signed ticket for one video, one person and one purpose."""
    content_type_id, object_id = _ref(video)
    return signing.dumps(
        {"t": content_type_id, "o": object_id, "u": user.pk, "p": purpose},
        salt=SALT, compress=True,
    )


def watch_url(video, user):
    """Where the player reads this video from. Minutes long."""
    return reverse("videos:play", args=[ticket(video, user, WATCH)])


def keep_url(video, user):
    """Where a copy is fetched from, for watching offline. Hours long,
    since a whole video comes down over it."""
    return reverse("videos:keep", args=[ticket(video, user, KEEP)])


def lifetime(purpose):
    if purpose == KEEP:
        return int(getattr(settings, "VIDEO_DOWNLOAD_LINK_SECONDS", 2 * 60 * 60))
    return int(getattr(settings, "VIDEO_LINK_SECONDS", 15 * 60))


def read_ticket(raw, purpose=WATCH):
    """What a ticket says, or None if it is not ours, is for something
    else, or has run out."""
    try:
        found = signing.loads(raw, salt=SALT, max_age=lifetime(purpose))
    except signing.BadSignature:
        return None
    if found.get("p") != purpose:
        return None
    return found


def video_from_ticket(found):
    """The lesson row the ticket points at, or None if it has gone."""
    content_type = ContentType.objects.filter(pk=found.get("t")).first()
    if content_type is None:
        return None
    model = content_type.model_class()
    if model is None or not hasattr(model, "video_source"):
        return None
    return model.objects.filter(pk=found.get("o")).first()
