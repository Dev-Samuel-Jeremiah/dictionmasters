"""
Word timings for the read-along highlight.

A recording doesn't say when each word is spoken, and spreading the words
evenly over its length drifts as soon as the reader slows down, pauses or
speeds up. So each recording is measured once:

1. ffmpeg pulls a small mono soundtrack out of the audio or video, from
   wherever it lives (R2, a URL, or local storage), and notes where the
   speaking actually happens — the runs between the silences.
2. ElevenLabs forced alignment matches the sound against the very text
   shown on the page and returns the start and end of every word. If
   ElevenLabs isn't set up or can't do it, Groq's Whisper transcribes it
   with word timestamps instead, told what the text should say so it
   hears the same words.
3. Both are saved as a ReadAlongTiming, with a quality score: how much of
   the page's text the recording really says. A recording that turns out
   to be reading something else scores low, and the page then follows the
   speech runs rather than words it can't trust.

The row is keyed by a fingerprint of the recording and the text, so an
edit to either is measured again.

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
import unicodedata
from difflib import SequenceMatcher
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
VERSION = "2"

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/forced-alignment"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_BYTES = 25 * 1024 * 1024
GROQ_PROMPT_LIMIT = 880   # Groq's own limit is 896 characters

EXTRACT_TIMEOUT = 15 * 60
API_TIMEOUT = 10 * 60
WORKING_FOR = timedelta(minutes=45)   # a run that's taken longer than this has died
RETRY_FAILED_AFTER = timedelta(hours=6)
PARAGRAPH_GAP = 1.4       # a silence this long reads as a new paragraph

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


# The field the page's words live in, where they can be replaced with what
# the recording actually says. A dialogue keeps its words in separate lines
# with speakers, so it isn't rewritten from here.
TEXT_FIELD = {
    "book.passage": "body",
    "book.conversation": "script",
    "echospell.passage": "body",
    "echospell.dialogue": None,
    "learning_modules.lessonitem": "body",
    "reading_club.chapter": "body",
}


def spoken_text(words):
    """What the recording says, as a paragraph: the words as transcribed,
    with a blank line wherever the reader left a long silence."""
    pieces = []
    last_end = None
    for text, start, end in words or []:
        if last_end is not None and start - last_end >= PARAGRAPH_GAP:
            pieces.append("\n\n")
        elif pieces:
            pieces.append(" ")
        pieces.append(str(text).strip())
        last_end = end
    return _sentence_case("".join(pieces).strip())


def _sentence_case(text):
    """Transcripts come back with the odd lower-case sentence start; a page of
    words should read properly."""
    out = []
    fresh = True
    for character in text:
        out.append(character.upper() if fresh and character.isalpha() else character)
        if character in ".!?\n":
            fresh = True
        elif not character.isspace():
            fresh = False
    return "".join(out)


def can_replace_text(obj):
    return bool(TEXT_FIELD.get(_label(obj)))


def replace_text_with_spoken(obj, timing):
    """Put the recording's own words on the page, so the highlight follows it
    word for word.

    The timing already measured belongs to exactly these words, so it is
    kept as it is rather than measured again: the page and the recording
    now say the same thing, word for word, by construction. Returns the
    new text, or "" if this kind of lesson can't be rewritten."""
    field = TEXT_FIELD.get(_label(obj))
    said = spoken_text(timing.words)
    if not field or not said:
        return ""
    setattr(obj, field, said)
    obj.save(update_fields=[field])

    timing.fingerprint = _fingerprint(obj)
    timing.quality = 1.0
    timing.status = timing.STATUS_READY
    timing.error = ""
    timing.save(update_fields=["fingerprint", "quality", "status", "error", "updated_at"])
    return said


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
    """(status, row) for `obj`. status is "ready", "pending" or
    "unavailable"; row is the ReadAlongTiming when ready. When nothing
    current exists, measuring starts in the background (unless
    `start` is False)."""
    from .models import ReadAlongTiming

    fingerprint = _fingerprint(obj)
    if not fingerprint:
        return "unavailable", None

    content_type = ContentType.objects.get_for_model(obj)
    row = ReadAlongTiming.objects.filter(content_type=content_type, object_id=obj.pk).first()
    now = timezone.now()

    if row and row.fingerprint == fingerprint:
        if row.status == ReadAlongTiming.STATUS_READY:
            return "ready", row
        if row.status == ReadAlongTiming.STATUS_WORKING and now - row.updated_at < WORKING_FOR:
            return "pending", None
        if row.status == ReadAlongTiming.STATUS_FAILED and now - row.updated_at < RETRY_FAILED_AFTER:
            return "unavailable", None

    if not start or not is_configured():
        return "unavailable", None

    if _claim(obj, content_type, row, fingerprint):
        _queue(obj)
    return "pending", None


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


def measure_in_background(obj):
    """Measure this recording again, without holding up the page."""
    _queue(obj)
    return True


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
    words, engine, runs, length = None, "", [], None
    try:
        with tempfile.TemporaryDirectory(prefix="read-along-") as folder:
            audio = _extract_audio(source, folder)
            length = _duration(audio)
            runs = speech_runs(audio, length)
            if getattr(settings, "ELEVENLABS_API_KEY", ""):
                try:
                    words, engine = _elevenlabs(audio, text), "elevenlabs"
                except AlignmentUnavailable as error:
                    errors.append(str(error))
            if words is None and getattr(settings, "GROQ_API_KEY", ""):
                # Whisper is told roughly what it should hear, so it comes
                # back with the page's own wording where it can. If that
                # upsets it, ask again plainly rather than lose the words.
                for hint in (text, ""):
                    try:
                        words, engine = _groq(audio, hint=hint), "groq"
                        break
                    except AlignmentUnavailable as error:
                        errors.append(str(error))
    except AlignmentUnavailable as error:
        errors.append(str(error))

    row.fingerprint = fingerprint
    row.speech = runs
    row.duration = length
    if words:
        row.status, row.engine, row.words, row.error = ReadAlongTiming.STATUS_READY, engine, words, ""
        row.quality = _spoken_share(text, words)
        if row.quality < ReadAlongTiming.MATCH_FLOOR:
            logger.warning(
                "Read-along: %s %s says only %.0f%% of its text — the recording and the text look different.",
                obj.__class__.__name__, obj.pk, row.quality * 100,
            )
    elif runs:
        # Nothing transcribable, but we still know when the voice speaks.
        row.status, row.engine, row.words, row.quality = ReadAlongTiming.STATUS_READY, "speech", [], 0.0
        row.error = ("; ".join(errors))[-255:]
    else:
        row.status, row.engine, row.words, row.quality = ReadAlongTiming.STATUS_FAILED, "", [], None
        row.error = ("; ".join(errors) or "No words came back.")[-255:]
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


_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")

SILENCE_DB = -32          # quieter than this counts as a pause
SILENCE_SECONDS = 0.32    # ...if it lasts at least this long
RUN_MIN_SECONDS = 0.25    # ignore clicks and breaths between words


def _duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, timeout=120, check=True,
        )
        return round(float(out.stdout.decode().strip()), 3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
        return None


def speech_runs(path, total=None):
    """[[start, end], …] for the stretches where someone is speaking.

    Even a recording nobody can transcribe gives this up, and it is what
    keeps the highlight still during a pause and moving during speech."""
    total = total or _duration(path)
    if not total:
        return []
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "info", "-i", path,
        "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_SECONDS}", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=EXTRACT_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return []
    log = result.stderr.decode(errors="ignore")
    starts = [float(value) for value in _SILENCE_START.findall(log)]
    ends = [float(value) for value in _SILENCE_END.findall(log)]

    # The gaps between the silences are the speech.
    runs = []
    at = 0.0
    for index, start in enumerate(starts):
        if start > at:
            runs.append([round(at, 3), round(min(start, total), 3)])
        at = ends[index] if index < len(ends) else total
    if at < total:
        runs.append([round(at, 3), round(total, 3)])
    return [run for run in runs if run[1] - run[0] >= RUN_MIN_SECONDS]


def _spoken_share(text, words):
    """How much of the page's text the recording actually says, 0–1.

    Matched the way the browser matches it: the longest runs the two have
    in common, in order. A recording that opens with "Hi, it's me, let's
    read together" and then reads the page still scores high — the
    greeting is simply extra."""
    said = [key for key in (_key(word[0]) for word in words) if key]
    page = [key for key in (_key(word) for word in text.split()) if key]
    if not page or not said:
        return 0.0
    blocks = SequenceMatcher(None, page, said, autojunk=False).get_matching_blocks()
    shared = sum(block.size for block in blocks)
    return round(min(shared / len(page), 1.0), 3)


_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}


def _as_number(key):
    """"three" and "3" are the same word to a listener, and so are
    "twenty-one" and "21". Returns the digits, or "" if it isn't a number."""
    if key in _ONES:
        return str(_ONES[key])
    if key in _TENS:
        return str(_TENS[key])
    for tens, value in _TENS.items():            # twentyone, fortyfive…
        if key.startswith(tens) and key[len(tens):] in _ONES:
            return str(value + _ONES[key[len(tens):]])
    return ""


def _key(word):
    key = re.sub(r"[^\w]", "", unicodedata.normalize("NFKD", str(word)).lower())
    return _as_number(key) or key


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


def _groq(audio_path, hint=""):
    fields = [
        ("model", GROQ_MODEL),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("language", "en"),
        ("temperature", "0"),
    ]
    if hint:
        # Whisper listens for these words in particular. Groq allows 896
        # characters of context, so the opening of the text is sent, cut
        # at a word so the last one isn't half a word.
        opening = " ".join(hint.split())[:GROQ_PROMPT_LIMIT]
        if len(opening) == GROQ_PROMPT_LIMIT and " " in opening:
            opening = opening.rsplit(" ", 1)[0]
        fields.append(("prompt", opening))
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
