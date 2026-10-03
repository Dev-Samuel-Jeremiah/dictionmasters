"""
Scan & Listen's saved readings (models.ScanReading).

    visible(user)                    the readings someone may find and play
    save(user, text, title, id)      keeps the text as it's scanned or typed
    start_audio(reading, user)       the read-aloud: reused if these exact
                                     words were read before, else made in the
                                     background with word timings for the
                                     read-along highlight
    search(user, q)                  the school's (and one's own) readings

The text is saved as it changes, so nothing is lost when the page is
closed. Audio is only ever made once for the same words in the same voice:
any reading with the same audio_hash, in any school, shares the recording.
"""

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models import ScanReading

logger = logging.getLogger(__name__)

MAX_CHARS = 24000
HOURLY_CHARS = 48000
STALE = timedelta(minutes=20)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scan-listen")


class ReadingError(Exception):
    """Something to tell the reader, in words they can act on."""


def visible(user):
    readings = ScanReading.objects.all()
    if user.is_staff:
        return readings
    shown = Q(owner=user)
    if user.school_id:
        shown |= Q(school_id=user.school_id)
    return readings.filter(shown)


def may_change(user, reading):
    """The person who made it, their school's admin, or staff."""
    return (user.is_staff or reading.owner_id == user.pk
            or (user.is_school_admin and reading.school_id and reading.school_id == user.school_id))


def tidy(text):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text or "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def spoken(text):
    """What the voice reads: the paragraphs, each on one line."""
    return "\n\n".join(" ".join(p.split()) for p in tidy(text).split("\n\n") if p.strip())


def _model():
    return getattr(settings, "BOOK_SCAN_VOICE_MODEL_ID", "") or settings.ELEVENLABS_MODEL_ID


def audio_hash(text):
    key = f"{settings.ELEVENLABS_VOICE_ID}|{_model()}|{spoken(text)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def title_for(text):
    first = next((line.strip() for line in tidy(text).split("\n") if line.strip()), "Scanned page")
    return (first[:77] + "…") if len(first) > 80 else first


def save(user, text, title="", reading_id=None):
    """The reading, saved: updated if it's this person's own, otherwise a
    new one (opening a school reading and changing it keeps the original)."""
    text = tidy(text)
    if not text:
        raise ReadingError("There's no text to save yet.")
    if len(text) > MAX_CHARS:
        raise ReadingError(f"A reading can be up to {MAX_CHARS:,} characters.")
    title = " ".join((title or "").split())[:200] or title_for(text)
    reading = None
    if reading_id:
        reading = ScanReading.objects.filter(pk=reading_id, owner=user).first()
    if reading is None:
        return ScanReading.objects.create(owner=user, school=user.school if user.school_id else None,
                                          title=title, text=text)
    if reading.text != text or reading.title != title:
        reading.text, reading.title = text, title
        reading.save(update_fields=["text", "title", "updated_at"])
    return reading


def search(user, query="", limit=20):
    readings = visible(user).select_related("owner")
    # Others see readings with audio; drafts are only their maker's.
    readings = readings.filter(Q(audio_status="ready") | Q(owner=user))
    query = " ".join(query.split())[:100]
    if query:
        readings = readings.filter(Q(title__icontains=query) | Q(text__icontains=query))
    return list(readings.order_by("-updated_at")[:limit])


def snippet(reading, query=""):
    text = " ".join(reading.text.split())
    if query:
        at = text.lower().find(query.lower())
        if at > 60:
            text = "…" + text[at - 40:]
    return text[:160] + ("…" if len(text) > 160 else "")


# ---------------------------------------------------------------------------
# The read-aloud
# ---------------------------------------------------------------------------

def _within_hourly_allowance(user, characters):
    if user.is_staff:
        return True
    key = f"book-scan-audio:{user.pk}:{int(time.time() // 3600)}"
    if cache.add(key, characters, timeout=3700):
        return characters <= HOURLY_CHARS
    try:
        return cache.incr(key, characters) <= HOURLY_CHARS
    except ValueError:
        return cache.add(key, characters, timeout=3700) and characters <= HOURLY_CHARS


def status_of(reading):
    if reading.audio_status == "working" and reading.audio_updated and reading.audio_updated < timezone.now() - STALE:
        return "failed"
    return reading.audio_status


def audio_is_current(reading):
    return reading.has_audio and reading.audio_text == spoken(reading.text)


def start_audio(reading, user):
    """"ready" (reused or already made) or "working" (being made)."""
    from apps.diction_library.narration import voice_configured

    if audio_is_current(reading):
        return "ready"
    if not voice_configured():
        raise ReadingError("Audio isn't set up on this site yet. Please contact your administrator.")
    text = spoken(reading.text)
    if not text:
        raise ReadingError("Add some text first.")
    wanted = audio_hash(reading.text)

    # These exact words, in this voice, were read before: use that recording.
    twin = ScanReading.objects.filter(audio_hash=wanted, audio_status="ready").exclude(audio_file="").exclude(pk=reading.pk).first()
    if twin is not None:
        _share(reading, twin)
        return "ready"

    if status_of(reading) == "working":
        return "working"
    if not _within_hourly_allowance(user, len(text)):
        raise ReadingError("This account has reached its audio allowance for this hour. Please try again later.")
    ScanReading.objects.filter(pk=reading.pk).update(audio_status="working", audio_error="", audio_updated=timezone.now())
    _run(reading.pk, text, wanted)
    return "working"


def _share(reading, twin):
    from django.contrib.contenttypes.models import ContentType

    from apps.book import read_along
    from apps.book.models import ReadAlongTiming

    reading.audio_file.name = twin.audio_file.name
    reading.audio_text, reading.audio_hash = twin.audio_text, twin.audio_hash
    reading.audio_duration, reading.audio_status, reading.audio_error = twin.audio_duration, "ready", ""
    reading.audio_updated = timezone.now()
    reading.save(update_fields=["audio_file", "audio_text", "audio_hash", "audio_duration", "audio_status",
                                "audio_error", "audio_updated"])
    timing = ReadAlongTiming.objects.filter(content_type=ContentType.objects.get_for_model(ScanReading),
                                            object_id=twin.pk).first()
    if timing:
        ReadAlongTiming.objects.update_or_create(
            content_type=ContentType.objects.get_for_model(ScanReading), object_id=reading.pk,
            defaults={"fingerprint": read_along._fingerprint(reading), "status": timing.status, "engine": timing.engine,
                      "words": timing.words, "speech": timing.speech, "duration": timing.duration,
                      "quality": timing.quality, "error": ""},
        )


def _run(reading_id, text, wanted):
    sync = getattr(settings, "SCAN_LISTEN_SYNC", False)        # tests: here, in this connection

    def work():
        if not sync:
            close_old_connections()
        try:
            _make(reading_id, text, wanted)
        except Exception:
            logger.exception("Scan & Listen audio failed for reading %s", reading_id)
            ScanReading.objects.filter(pk=reading_id, audio_status="working").update(
                audio_status="failed", audio_updated=timezone.now(),
                audio_error="Something went wrong. Please try again.")
        finally:
            if not sync:
                close_old_connections()

    if sync:
        work()
    else:
        _pool.submit(work)


def _make(reading_id, text, wanted):
    from django.core.files.base import ContentFile

    from apps.diction_library import narration

    reading = ScanReading.objects.get(pk=reading_id)
    try:
        audio, words, duration = narration.read_chapter(text.split("\n\n"), model=_model())
    except narration.NarrationUnavailable as error:
        logger.warning("Scan & Listen audio for reading %s failed: %s", reading_id, error)
        ScanReading.objects.filter(pk=reading_id).update(
            audio_status="failed", audio_updated=timezone.now(),
            audio_error="The voice service didn't answer. Please try again in a few minutes.")
        return
    old = reading.audio_file.name if reading.audio_file else ""
    reading.audio_file.save(f"{slugify(reading.title)[:60] or 'reading'}.mp3", ContentFile(audio), save=False)
    reading.audio_text, reading.audio_hash = text, wanted
    reading.audio_duration, reading.audio_status, reading.audio_error = round(duration, 2), "ready", ""
    reading.audio_updated = timezone.now()
    reading.save(update_fields=["audio_file", "audio_text", "audio_hash", "audio_duration", "audio_status",
                                "audio_error", "audio_updated"])
    narration._save_timing(reading, words, duration)
    if old and old != reading.audio_file.name:
        forget_file(old, reading.audio_file.storage)


def forget_file(name, storage):
    """Delete a recording no reading uses any more."""
    if name and not ScanReading.objects.filter(audio_file=name).exists():
        try:
            storage.delete(name)
        except Exception:
            logger.warning("Couldn't delete %s", name)


def delete(reading):
    from django.contrib.contenttypes.models import ContentType

    from apps.book.models import ReadAlongTiming

    name, storage = (reading.audio_file.name, reading.audio_file.storage) if reading.audio_file else ("", None)
    ReadAlongTiming.objects.filter(content_type=ContentType.objects.get_for_model(ScanReading), object_id=reading.pk).delete()
    reading.delete()
    if name:
        forget_file(name, storage)
