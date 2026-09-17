"""
Word timings for the read-along highlight.

A recording doesn't say when each word is spoken, and spreading the words
evenly over its length drifts as soon as the reader slows down, pauses or
speeds up. So each recording is measured once:

1. ffmpeg pulls a small mono soundtrack out of the audio or video, from
   wherever it lives (R2, a URL, or local storage).
2. ElevenLabs forced alignment matches it against the very text shown on
   the page and returns the start and end of every word. If ElevenLabs
   isn't set up or can't do it, Groq's Whisper transcribes it with word
   timestamps instead.
3. The words are saved as a ReadAlongTiming, keyed by a fingerprint of
   the recording and the text, so an edit to either is measured again.

It all happens in the background the first time someone opens the page,
so nobody waits for it; until it's ready the page uses its estimate. The
browser lines the measured words up with the words on the page (see
static/js/read_along.js), so small differences in punctuation or a word
the recording skips never throw it off.

    python manage.py sync_read_along     # measure everything now
"""

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.db import IntegrityError, close_old_connections
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

# Bump to measure everything again after a change to how it's done.
VERSION = "1"

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/forced-alignment"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_BYTES = 25 * 1024 * 1024

EXTRACT_TIMEOUT = 15 * 60
API_TIMEOUT = 10 * 60
WORKING_FOR = timedelta(minutes=45)   # a run that's taken longer than this has died
RETRY_FAILED_AFTER = timedelta(hours=6)

SIGNING_SALT = "dm-read-along"

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="read-along")
_queued = set()
_queued_lock = threading.Lock()


class AlignmentUnavailable(Exception):
    """This recording couldn't be measured this time."""


# ---------------------------------------------------------------------------
# What can be read along with, and the words each one shows
# ---------------------------------------------------------------------------

_SPEAKER_LABEL = re.compile(r"^\s*[^\s:]{1,20}\s*:\s*", re.MULTILINE)


def _without_speaker_labels(script):
    # "A: Good morning!" — the recording says the words, not the "A:".
    return _SPEAKER_LABEL.sub("", script or "")


TEXT_FOR = {
    "book.passage": lambda obj: obj.body,
    "book.conversation": lambda obj: _without_speaker_labels(obj.script),
    "echospell.passage": lambda obj: obj.body,
    "echospell.dialogue": lambda obj: "\n".join(line.text for line in obj.lines.all()),
    "learning_modules.lessonitem": lambda obj: obj.body,
    "reading_club.chapter": lambda obj: obj.body,
}


def _label(obj):
    return f"{obj._meta.app_label}.{obj._meta.model_name}"


def text_for(obj):
    getter = TEXT_FOR.get(_label(obj))
    return (getter(obj) or "").strip() if getter else ""


def _media(obj):
    """(identity, where ffmpeg reads it) for the recording the words follow:
    the audio if there is any, otherwise the video — the same choice the
    page makes."""
    for file_field, url_field in (("audio_file", "audio_url"), ("video_file", "video_url")):
        stored = getattr(obj, file_field, None)
        url = getattr(obj, url_field, "") or ""
        if url:
            return url, url
        if stored:
            try:
                return stored.name, stored.path
            except (NotImplementedError, ValueError):
                return stored.name, stored.url
    return "", ""


def _fingerprint(obj):
    identity, _source = _media(obj)
    text = text_for(obj)
    if not identity or not text:
        return ""
    return hashlib.sha256(f"{VERSION}|{identity}|{text}".encode("utf-8")).hexdigest()


def is_configured():
    return bool(shutil.which("ffmpeg")) and bool(
        getattr(settings, "ELEVENLABS_API_KEY", "") or getattr(settings, "GROQ_API_KEY", "")
    )


# ---------------------------------------------------------------------------
# The page's side: a signed address to ask for the timings
# ---------------------------------------------------------------------------

def sync_url(obj):
    """Where the page fetches this object's timings. Signed, so only a page
    that was allowed to show the object can ask for its words."""
    if _label(obj) not in TEXT_FOR or not obj.pk:
        return ""
    token = signing.dumps([_label(obj), obj.pk], salt=SIGNING_SALT, compress=True)
    return reverse("book:read_along", args=[token])


def object_for_token(token):
    from django.apps import apps

    try:
        label, pk = signing.loads(token, salt=SIGNING_SALT)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if label not in TEXT_FOR:
        return None
    try:
        model = apps.get_model(label)
    except LookupError:
        return None
    return model.objects.filter(pk=pk).first()


def timing_for(obj, start=True):
    """(status, words) for `obj`. status is "ready", "pending" or
    "unavailable". When nothing current exists, measuring starts in the
    background (unless `start` is False)."""
    from .models import ReadAlongTiming

    fingerprint = _fingerprint(obj)
    if not fingerprint:
        return "unavailable", []

    content_type = ContentType.objects.get_for_model(obj)
    row = ReadAlongTiming.objects.filter(content_type=content_type, object_id=obj.pk).first()
    now = timezone.now()

    if row and row.fingerprint == fingerprint:
        if row.status == ReadAlongTiming.STATUS_READY:
            return "ready", row.words
        if row.status == ReadAlongTiming.STATUS_WORKING and now - row.updated_at < WORKING_FOR:
            return "pending", []
        if row.status == ReadAlongTiming.STATUS_FAILED and now - row.updated_at < RETRY_FAILED_AFTER:
            return "unavailable", []

    if not start or not is_configured():
        return "unavailable", []

    if _claim(obj, content_type, row, fingerprint):
        _queue(obj)
    return "pending", []


def _claim(obj, content_type, row, fingerprint):
    """Mark the timing as being worked on. Only one process wins, so two
    visitors opening the page at once don't measure it twice."""
    from .models import ReadAlongTiming

    if row is None:
        try:
            ReadAlongTiming.objects.create(content_type=content_type, object_id=obj.pk, fingerprint=fingerprint)
            return True
        except IntegrityError:
            row = ReadAlongTiming.objects.filter(content_type=content_type, object_id=obj.pk).first()
            if row is None:
                return False
    claimed = ReadAlongTiming.objects.filter(pk=row.pk, updated_at=row.updated_at).update(
        fingerprint=fingerprint, status=ReadAlongTiming.STATUS_WORKING, error="", updated_at=timezone.now()
    )
    return bool(claimed)


def _queue(obj):
    key = (_label(obj), obj.pk)
    with _queued_lock:
        if key in _queued:
            return
        _queued.add(key)
    model, pk = obj.__class__, obj.pk

    def run():
        close_old_connections()
        try:
            fresh = model.objects.filter(pk=pk).first()
            if fresh is not None:
                measure(fresh)
        except Exception:                     # never let a timing take anything else down
            logger.exception("Read-along timing failed for %s %s", model.__name__, pk)
        finally:
            with _queued_lock:
                _queued.discard(key)
            close_old_connections()

    _pool.submit(run)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def measure(obj):
    """Measure `obj` now and save the result. Returns the ReadAlongTiming."""
    from .models import ReadAlongTiming

    fingerprint = _fingerprint(obj)
    content_type = ContentType.objects.get_for_model(obj)
    row, _created = ReadAlongTiming.objects.get_or_create(
        content_type=content_type, object_id=obj.pk, defaults={"fingerprint": fingerprint}
    )
    if not fingerprint:
        row.delete()
        return None

    text = text_for(obj)
    _identity, source = _media(obj)
    errors = []
    words, engine = None, ""
    try:
        with tempfile.TemporaryDirectory(prefix="read-along-") as folder:
            audio = _extract_audio(source, folder)
            if getattr(settings, "ELEVENLABS_API_KEY", ""):
                try:
                    words, engine = _elevenlabs(audio, text), "elevenlabs"
                except AlignmentUnavailable as error:
                    errors.append(str(error))
            if words is None and getattr(settings, "GROQ_API_KEY", ""):
                try:
                    words, engine = _groq(audio), "groq"
                except AlignmentUnavailable as error:
                    errors.append(str(error))
    except AlignmentUnavailable as error:
        errors.append(str(error))

    row.fingerprint = fingerprint
    if words:
        row.status, row.engine, row.words, row.error = ReadAlongTiming.STATUS_READY, engine, words, ""
    else:
        row.status, row.engine, row.words = ReadAlongTiming.STATUS_FAILED, "", []
        row.error = ("; ".join(errors) or "No words came back.")[:255]
        logger.warning("No read-along timing for %s %s: %s", obj.__class__.__name__, obj.pk, row.error)
    row.save()
    return row


def _extract_audio(source, folder):
    """A small mono MP3 of the soundtrack — quick to upload, and well
    inside every service's size limit even for a long chapter."""
    if not shutil.which("ffmpeg"):
        raise AlignmentUnavailable("ffmpeg isn't installed.")
    out = f"{folder}/speech.mp3"
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-i", source,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        out,
    ]
    try:
        subprocess.run(command, capture_output=True, timeout=EXTRACT_TIMEOUT, check=True)
    except subprocess.TimeoutExpired as error:
        raise AlignmentUnavailable("Reading the recording took too long.") from error
    except (subprocess.CalledProcessError, OSError) as error:
        detail = getattr(error, "stderr", b"") or b""
        raise AlignmentUnavailable(f"Couldn't read the recording: {detail.decode(errors='ignore')[:120]}") from error
    return out


def _multipart(fields, file_field, file_path):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    with open(file_path, "rb") as handle:
        audio = handle.read()
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="speech.mp3"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n".encode("utf-8")
    )
    parts.append(audio)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}", len(audio)


def _post(url, headers, body, content_type, service):
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={**headers, "Content-Type": content_type, "Accept": "application/json", "User-Agent": "dictionmasters/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read()[:200].decode("utf-8", errors="ignore")
        raise AlignmentUnavailable(f"{service} answered HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise AlignmentUnavailable(f"Couldn't reach {service}.") from error


def _clean(words):
    """[[word, start, end], …] with blanks dropped and times kept in order."""
    cleaned = []
    last = 0.0
    for text, start, end in words:
        text = str(text or "").strip()
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if not text or start != start or end != end:     # NaN check
            continue
        start = max(start, last)
        end = max(end, start)
        cleaned.append([text, round(start, 3), round(end, 3)])
        last = start
    return cleaned


def _elevenlabs(audio_path, text):
    body, content_type, _size = _multipart([("text", text)], "file", audio_path)
    data = _post(ELEVENLABS_URL, {"xi-api-key": settings.ELEVENLABS_API_KEY}, body, content_type, "ElevenLabs")
    words = _clean((w.get("text"), w.get("start"), w.get("end")) for w in data.get("words") or [])
    if not words:
        raise AlignmentUnavailable("ElevenLabs returned no words.")
    return words


def _groq(audio_path):
    fields = [
        ("model", GROQ_MODEL),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("language", "en"),
        ("temperature", "0"),
    ]
    body, content_type, size = _multipart(fields, "file", audio_path)
    if size > GROQ_MAX_BYTES:
        raise AlignmentUnavailable("The recording is too long for Groq.")
    data = _post(GROQ_URL, {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}, body, content_type, "Groq")
    words = _clean((w.get("word"), w.get("start"), w.get("end")) for w in data.get("words") or [])
    if not words:
        raise AlignmentUnavailable("Groq returned no words.")
    return words


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------

def candidates():
    """Every object that has text and a recording to read along with."""
    from django.apps import apps
    from django.db.models import Q

    for label in TEXT_FOR:
        model = apps.get_model(label)
        names = {f.name for f in model._meta.fields}
        has_media = Q()
        for field in ("audio_file", "audio_url", "video_file", "video_url"):
            if field in names:
                has_media |= ~Q(**{field: ""})
        for obj in model.objects.filter(has_media):
            if _fingerprint(obj):
                yield obj
