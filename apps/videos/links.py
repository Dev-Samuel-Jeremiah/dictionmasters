"""
The address a lesson video, or a lesson recording, is played from.

The browser never sees where a video really lives. It gets a link to
this site carrying a signed ticket that says which video, for which
signed-in person, and for how long. Django checks the ticket and the
person's access, then reads the bytes out of private R2 storage and
passes them on (see views.py).

A ticket copied out of the page is useless to anyone else: it is tied to
the account it was made for, and it stops working within minutes.

Recordings (audio) travel the same way, so they can be saved for offline
listening like videos: a ticket for one says "m": "a", and its file is the
row's audio_file. A row can hold both, e.g. a recital's video and its model
recording, each saved on its own. An EchoSpell card's second recording, its
"Quick" one (quick_audio_file), says "m": "q". Tickets made before
recordings could be saved carry no "m" and mean the video.
"""

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.urls import reverse

SALT = "dm.video.link"
WATCH = "watch"
KEEP = "keep"

VIDEO = "video"
AUDIO = "audio"
QUICK = "quick"
FIELDS = {VIDEO: "video_file", AUDIO: "audio_file", QUICK: "quick_audio_file"}
MARKS = {AUDIO: "a", QUICK: "q"}


def _ref(video):
    return ContentType.objects.get_for_model(video).pk, video.pk


def stored_file(entry, media=VIDEO):
    """The stored file behind a row, for this kind of media, or None.

    Most rows keep theirs in video_file / audio_file (book.VideoContent,
    book.AudioContent). A row that keeps it elsewhere (a Diction Library
    item's one "file") says so with offline_file(media)."""
    if entry is None:
        return None
    if hasattr(entry, "offline_file"):
        found = entry.offline_file(media)
    else:
        found = getattr(entry, FIELDS.get(media, "video_file"), None)
    return found or None


def media_of(found):
    """Which file a ticket is for: tickets without "m" are for the video."""
    return {mark: media for media, mark in MARKS.items()}.get(found.get("m"), VIDEO)


def ticket(video, user, purpose=WATCH, media=VIDEO):
    """A signed ticket for one video (or recording), one person and one purpose."""
    content_type_id, object_id = _ref(video)
    data = {"t": content_type_id, "o": object_id, "u": user.pk, "p": purpose}
    if media in MARKS:
        data["m"] = MARKS[media]
    return signing.dumps(data, salt=SALT, compress=True)


def watch_url(video, user, media=VIDEO):
    """Where the player reads this video from. Minutes long."""
    return reverse("videos:play", args=[ticket(video, user, WATCH, media)])


def keep_url(video, user, media=VIDEO):
    """Where a copy is fetched from, for watching offline. Hours long,
    since a whole video comes down over it."""
    return reverse("videos:keep", args=[ticket(video, user, KEEP, media)])


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
    if model is None or not any(hasattr(model, name) for name in ("video_source", "audio_source", "offline_file")):
        return None
    return model.objects.filter(pk=found.get("o")).first()
