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
   ElevenLabs isn't set up or can't do it, OpenAI's Whisper transcribes it
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
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from difflib import SequenceMatcher
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.db import IntegrityError, close_old_connections
from django.urls import reverse
from django.utils import timezone

from apps.manage.rich_text import plain_text

logger = logging.getLogger(__name__)

# Bump to measure everything again after a change to how it's done.
VERSION = "2"

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/forced-alignment"
OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_MAX_BYTES = 25 * 1024 * 1024        # OpenAI's own limit
OPENAI_PROMPT_LIMIT = 880                  # ~224 tokens, the prompt's limit

EXTRACT_TIMEOUT = 15 * 60
API_TIMEOUT = 10 * 60
WORKING_FOR = timedelta(minutes=45)   # a run that's taken longer than this has died
RETRY_FAILED_AFTER = timedelta(hours=6)
PARAGRAPH_GAP = 1.4       # a silence this long reads as a new paragraph
DROPPED_VOICE = 1.5       # this much voice with no words heard means the transcriber skipped it
WORD_MAX = 2.0            # no single word takes longer than this to say
GAP_PAD = 0.8             # seconds either side of a skipped stretch, so no word is cut in half
RATE_LIMIT_TRIES = 4      # told to slow down: wait and try again, this many attempts in all

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


# Rich text fields are aligned by their words, never their markup.
TEXT_FOR = {
    "book.passage": lambda obj: plain_text(obj.body),
    "book.conversation": lambda obj: _without_speaker_labels(obj.script),
    "echospell.passage": lambda obj: plain_text(obj.body),
    "echospell.dialogue": lambda obj: "\n".join(plain_text(line.text) for line in obj.lines.all()),
    "learning_modules.lessonitem": lambda obj: plain_text(obj.body),
    "reading_club.chapter": lambda obj: plain_text(obj.body),
    "assembly_recitals.recital": lambda obj: "\n".join(" ".join(verse) for verse in obj.verses),
    "conversational_dialogue.dialogue": lambda obj: "\n".join(text for _speaker, text in obj.lines),
    "book.sentencepractice": lambda obj: plain_text(obj.sentence),
    "book.tonguetwister": lambda obj: plain_text(obj.text),
    "diction_radio.radioepisode": lambda obj: plain_text(obj.transcript),
    # An EchoSpell card's recordings read its words out one by one: "Full"
    # here, "Quick" filed separately (echospell.CardLessonQuick).
    "echospell.cardlesson": lambda obj: "\n".join(obj.word_list),
    "echospell.cardlessonquick": lambda obj: "\n".join(obj.word_list),
    # A Diction Library book, read aloud a chapter at a time.
    "diction_library.librarychapter": lambda obj: obj.text,
    # A teacher's lesson note, read aloud (apps/lesson_audio): what the voice read.
    "lesson_audio.lessonnote": lambda obj: obj.audio_text,
    # A Scan & Listen reading (apps/learning_tools): what the voice read.
    "learning_tools.scanreading": lambda obj: obj.audio_text,
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
    "assembly_recitals.recital": None,
    "conversational_dialogue.dialogue": None,
    "book.sentencepractice": "sentence",
    "book.tonguetwister": "text",
    "diction_radio.radioepisode": "transcript",
    "echospell.cardlesson": None,
    "echospell.cardlessonquick": None,
    "diction_library.librarychapter": None,
    "lesson_audio.lessonnote": None,
    "learning_tools.scanreading": None,
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


def coverage(text, words):
    """Which parts of the page the recording actually reads: how many words
    it says, and how many it never reaches at the start and the end."""
    page = [key for key in (_key(word) for word in text.split()) if key]
    said = [key for key in (_key(word[0]) for word in words) if key]
    if not page:
        return {"words": 0, "matched": 0, "head": 0, "tail": 0}
    found = SequenceMatcher(None, page, said, autojunk=False).get_matching_blocks()
    # A lone word matching somewhere is a coincidence; a run of two or more
    # is the reading. Only runs say where the recording starts and stops.
    blocks = [block for block in found if block.size >= 2]
    if not blocks:
        return {"words": len(page), "matched": 0, "head": len(page), "tail": 0}
    first, last = blocks[0], blocks[-1]
    return {
        "words": len(page),
        "matched": sum(block.size for block in found),
        "head": first.a,
        "tail": len(page) - (last.a + last.size),
    }


def trim_to_spoken(obj, timing):
    """Cut the text down to the part the recording actually reads — the
    opening it skips and the ending it stops short of go — keeping the
    text's own wording, spelling and line breaks exactly as written.

    The timing already belongs to these words, so it's kept rather than
    measured again. Returns the number of words removed (0 if nothing was
    unread, or this kind of lesson can't be edited here)."""
    field = TEXT_FIELD.get(_label(obj))
    text = getattr(obj, field, "") if field else ""
    if not text:
        return 0
    cover = coverage(text_for(obj), timing.words)
    if not (cover["head"] or cover["tail"]):
        return 0

    # Each word's place in the original text, counting only real words the
    # same way the matching does, so punctuation-only pieces stay attached.
    spans = [match.span() for match in re.finditer(r"\S+", text) if _key(match.group())]
    keep_from = cover["head"]
    keep_to = len(spans) - cover["tail"]
    if keep_from >= keep_to:
        return 0
    start = spans[keep_from][0]
    end = spans[keep_to - 1][1]
    trimmed = text[start:end].strip()

    setattr(obj, field, trimmed)
    obj.save(update_fields=[field])
    timing.fingerprint = _fingerprint(obj)
    timing.quality = _spoken_share(text_for(obj), timing.words)
    timing.save(update_fields=["fingerprint", "quality", "updated_at"])
    return cover["head"] + cover["tail"]


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


# Where a model keeps the recording its words follow, in order of choice. A
# model can say otherwise with READ_ALONG_MEDIA (e.g. a card's Quick one).
MEDIA_FIELDS = (("audio_file", "audio_url"), ("video_file", "video_url"))


def _media_fields(obj_or_model):
    return getattr(obj_or_model, "READ_ALONG_MEDIA", MEDIA_FIELDS)


def _content_type(obj):
    # Stand-ins like CardLessonQuick keep timings of their own.
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def _media(obj):
    """(identity, where ffmpeg reads it) for the recording the words follow:
    the audio if there is any, otherwise the video — the same choice the
    page makes."""
    for file_field, url_field in _media_fields(obj):
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


# Word lists are placed item by item (list_timing); bumping this measures
# them again without touching passages.
LIST_VERSION = "L2"


def _fingerprint(obj, version=None):
    identity, _source = _media(obj)
    text = text_for(obj)
    if not identity or not text:
        return ""
    if version is None:
        version = VERSION + (LIST_VERSION if _label(obj) in TAP_ALONG else "")
    return hashlib.sha256(f"{version}|{identity}|{text}".encode("utf-8")).hexdigest()


def is_configured():
    return bool(shutil.which("ffmpeg")) and bool(
        getattr(settings, "ELEVENLABS_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "")
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


# ---------------------------------------------------------------------------
# Timing set by hand ("Tap along" in the control room)
# ---------------------------------------------------------------------------

# Word lists, read one item at a time: an admin can time them exactly by
# tapping as each item is said. A long, slow recording (a word spelled out,
# repeated and used in a sentence) is where automatic timing is least sure.
TAP_ALONG = {"echospell.cardlesson", "echospell.cardlessonquick"}
MANUAL = "manual"


# ---------------------------------------------------------------------------
# Word lists: each item found on its own
# ---------------------------------------------------------------------------

# A spelling card's Full recording is a lesson, not a reading: "Hello
# friends… Number one: Today. Today. T-O-D-A-Y. Please don't say…". The
# passage matcher (which forgives near-spellings and favours words heard
# side by side) latches onto the wrong moment there — "that" sounds like
# "today". So for a list each item is placed here instead, strictly:
#   1. the teacher's own numbering — the word said right after "number 12"
#      (or a bare "12") is item 12, however it was heard;
#   2. otherwise the first time the item itself is said after the one before;
#   3. both transcripts are used, so a word one of them missed isn't lost;
#   4. the start is pulled back to where the voice starts saying it.
_NUMBER_WORDS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive "
    "twentysix twentyseven twentyeight twentynine thirty".split())}


def _norm(word):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(word)).lower())


def _as_count(key):
    if key.isdigit():
        return int(key)
    return _NUMBER_WORDS.get(key)


def _close_enough(item, heard):
    # Exact, or one letter out for a longer word ("breakfast"/"brekfast");
    # never the loose sound-alike match passages use.
    if item == heard:
        return True
    if len(item) < 5 or abs(len(item) - len(heard)) > 1:
        return False
    return SequenceMatcher(None, item, heard).ratio() >= 0.88


def _list_marks(items, transcript):
    """For each item, from one transcript: (when its number is said, when
    the item itself is first said, when the number ends), each None if not
    heard, always after the item before."""
    heard = [(_norm(w), float(a), float(b)) for w, a, b in transcript if _norm(w)]
    keys = [h[0] for h in heard]
    marks, after = [], -1.0
    for number, item in enumerate(items, start=1):
        first = _norm(item.split()[0]) if item.split() else ""
        numbered = numbered_end = None
        for i, key in enumerate(keys):
            if heard[i][1] <= after or _as_count(key) != number:
                continue
            if (i > 0 and keys[i - 1] == "number") or key.isdigit():
                numbered, numbered_end = heard[i][1], heard[i][2]
                break
        said = next((h[1] for h in heard if h[1] > max(after, (numbered or after) - 0.5) and _close_enough(first, h[0])), None)
        if said is not None and numbered is not None and said - numbered > 15:
            said = None                          # that's a later mention, not this item
        marks.append((numbered, said, numbered_end))
        after = max(t for t in (numbered, said, after) if t is not None)
    return marks


EDGE = 0.4          # a word time this close to a stretch of speech belongs to it


def _run_index(runs, moment):
    """The stretch of speech `moment` falls in (or just before), or None."""
    best = None
    for i, (a, b) in enumerate(runs):
        if a - 0.15 <= moment <= b + 0.15:
            return i
        if a <= moment:
            best = i
    return best


def list_timing(items, transcripts, runs=()):
    """When each item of a word list starts (seconds), using every
    transcript heard and the stretches where the voice speaks, and how
    many were placed from what was heard.

    Transcripts are close about which word is where but loose about the
    exact second; the stretches of speech are exact. A teacher says
    "Number two", pauses, then "Breakfast" — so the item starts where the
    voice starts again after its number."""
    runs = [(float(a), float(b)) for a, b in runs or ()]
    tries = [_list_marks(items, t) for t in transcripts if t]
    heard_times = sorted({float(w[1]) for t in transcripts if t for w in t})
    heard_words = [(_norm(w[0]), float(w[1])) for t in transcripts if t for w in t if _norm(w[0])]

    def begins(run_start, t):
        # Nothing else was heard between the start of this stretch of speech
        # and the word: the word is what starts it (transcript times run late).
        return not any(run_start - EDGE <= h < t - 0.05 for h in heard_times)

    starts, previous = [], -1.0
    for k in range(len(items)):
        item_key = _norm(items[k].split()[0]) if items[k].split() else ""
        numbers = sorted(m[k][0] for m in tries if m[k][0] is not None and m[k][0] > previous)
        # When the number has finished being said: a long one ("thirteen")
        # can be split in two by a breath, and its tail isn't the word.
        number_end = max([m[k][2] for m in tries if m[k][0] is not None and m[k][2] is not None
                          and numbers and m[k][0] <= numbers[0] + 1.0] or [0.0])
        saids = sorted(m[k][1] for m in tries if m[k][1] is not None and m[k][1] > previous)
        start = None
        if numbers:
            spoken = numbers[0]
            at = _run_index(runs, spoken) if runs else None
            if at is None:
                start = next((t for t in saids if 0 < t - spoken <= 15), None)
            else:
                a, b = runs[at]
                # 1. Said in the same breath as its number ("…eleven, cup"):
                #    only if that breath is long enough to hold both.
                same = [t for t in saids if spoken < t and a - EDGE <= t <= b + EDGE]
                if same and (same[0] < b - 0.15 or b - a >= 1.0):
                    start = max(a, min(same[0] - 0.05, max(spoken + 0.4, (spoken + b) / 2)))
                # 2. The next time the voice speaks after the number is the
                #    word — "Number two … Breakfast" — unless what was heard
                #    there is other talk ("How do you pronounce this word?").
                if start is None:
                    following = next((r for r in runs[at + 1:] if r[0] > max(b, number_end - 0.15)), None)
                    if following and following[0] - spoken <= 10:
                        there = [key for key, h in heard_words if following[0] - EDGE <= h <= following[1] + EDGE]
                        if not there or any(_close_enough(item_key, key) for key in there):
                            start = following[0]
                # 3. Otherwise the word itself, where the voice really is
                #    speaking (a time in a silence is a loose one).
                if start is None:
                    for t in saids:
                        if not 0 < t - spoken <= 15:
                            continue
                        where = _run_index(runs, t)
                        if where is not None and not (runs[where][0] - EDGE <= t <= runs[where][1] + EDGE):
                            ahead = where + 1 if where + 1 < len(runs) else None
                            where = ahead if ahead is not None and runs[ahead][0] - EDGE <= t else None
                        if where is None or where == at:
                            continue
                        ra_, rb_ = runs[where]
                        start = ra_ if (t - ra_ <= 0.8 or begins(ra_, t)) else t - 0.05
                        break
                # 4. Nothing better: where the voice starts again.
                if start is None:
                    following = next((r for r in runs[at + 1:] if r[0] > max(b, number_end - 0.15)), None)
                    if following and following[0] - spoken <= 10:
                        start = following[0]
        if start is None and saids:
            t = saids[0]
            at = _run_index(runs, t) if runs else None
            start = t
            if at is not None:
                a, b = runs[at]
                if a <= t <= b + 0.15 and (t - a <= 0.8 or begins(a, t)):
                    start = a                  # the voice starts the word here
                elif t > b:
                    later = next((r for r in runs[at + 1:]), None)
                    if later and later[0] - t <= 1.5:
                        start = later[0]
        if start is not None and start <= previous:
            start = None
        starts.append(start)
        if start is not None:
            previous = start
    placed = sum(1 for s in starts if s is not None)
    # Anything not heard at all: the stretch of speech nobody transcribed
    # between its neighbours, or else halfway between them.
    for k, start in enumerate(starts):
        if start is not None:
            continue
        before = next((starts[j] for j in range(k - 1, -1, -1) if starts[j] is not None), 0.0)
        after = next((starts[j] for j in range(k + 1, len(starts)) if starts[j] is not None), None)
        gap = [r for r in runs if r[0] > before + 0.6 and (after is None or r[1] < after - 0.3)]
        heard_at = {round(float(w[1]), 1) for t in transcripts if t for w in t}
        unheard = [r for r in gap if not any(r[0] - EDGE <= h <= r[1] + EDGE for h in heard_at)]
        if unheard:
            starts[k] = unheard[0][0]
        elif gap:
            starts[k] = gap[0][0]
        else:
            starts[k] = before + 1.0 if after is None else (before + after) / 2
    return starts, placed


def _item_words(items, starts, duration):
    """[[word, start, end], …] for list items starting at `starts`."""
    words = []
    for n, (item, start) in enumerate(zip(items, starts)):
        stop = starts[n + 1] if n + 1 < len(starts) else (duration or start + 2.0)
        span = max(0.3, min(stop - start, 2.0))
        parts = item.split()
        for k, part in enumerate(parts):
            a = start + span * k / len(parts)
            words.append([part, round(a, 3), round(a + span / len(parts), 3)])
    return words


def can_tap_along(obj):
    return _label(obj) in TAP_ALONG


def tap_items(obj):
    """What gets one tap each: the items of the list, in order."""
    return [line.strip() for line in text_for(obj).splitlines() if line.strip()]


def recording_name(obj):
    """Which recording a row is about, when a lesson has more than one."""
    return {"echospell.cardlesson": "Full recording", "echospell.cardlessonquick": "Quick recording"}.get(_label(obj), "")


def media_url(obj):
    """An address the browser can play for the recording the words follow."""
    for file_field, url_field in _media_fields(obj):
        url = getattr(obj, url_field, "") or ""
        if url:
            return url
        stored = getattr(obj, file_field, None)
        if stored:
            return stored.url
    return ""


def save_tapped(obj, starts):
    """Keep timings tapped by hand: one start (seconds) per item. Each item
    runs until the next one starts. Returns the ReadAlongTiming."""
    from .models import ReadAlongTiming

    items = tap_items(obj)
    if len(starts) != len(items):
        raise ValueError(f"Expected {len(items)} taps, got {len(starts)}.")
    starts = [max(0.0, float(t)) for t in starts]
    if any(later < earlier for earlier, later in zip(starts, starts[1:])):
        raise ValueError("The taps must go forward in time.")
    content_type = _content_type(obj)
    row, _created = ReadAlongTiming.objects.get_or_create(
        content_type=content_type, object_id=obj.pk, defaults={"fingerprint": _fingerprint(obj)}
    )
    words = _item_words(items, starts, row.duration)
    row.fingerprint = _fingerprint(obj)
    row.status, row.engine, row.words, row.quality, row.error = ReadAlongTiming.STATUS_READY, MANUAL, words, 1.0, ""
    row.save()
    return row


def explain(error):
    """A service error in plain words, with what to do about it."""
    text = (error or "").lower()
    if not text:
        return ""
    if "insufficient_quota" in text or "quota" in text or "billing" in text or "credit" in text:
        return ("The word service's account has run out of credit. Add credit (OpenAI: platform.openai.com → "
                "Settings → Billing), then press “Measure everything again” below.")
    if "http 401" in text or "invalid_api_key" in text or "incorrect api key" in text:
        return "The word service's API key is wrong or has been revoked. Put a working key in the server's settings (.env), restart, then measure again."
    if "http 429" in text:
        return "The word service is limiting how fast it can be used. Wait a few minutes, then measure again."
    if "too long" in text:
        return "Some recordings are too long for the word service (over 25 MB once converted). Split them into shorter recordings."
    if "couldn't reach" in text or "timed out" in text:
        return "The server couldn't reach the word service (a network problem). Try measuring again later."
    return "The word service couldn't measure the words. The details are below."


def _self_timed(obj):
    check = getattr(obj, "read_along_self_timed", None)
    return bool(check and check())


def needs_retry(row):
    """Only the voice's pauses were kept because the word service failed
    (no credit, a timeout…): usable, but worth measuring again later. A
    recording with no speakable words at all has no error and isn't retried."""
    return row.engine == "speech" and bool(row.error)


def timing_for(obj, start=True):
    """(status, row) for `obj`. status is "ready", "pending" or
    "unavailable"; row is the ReadAlongTiming when ready. When nothing
    current exists, measuring starts in the background (unless
    `start` is False)."""
    from .models import ReadAlongTiming

    fingerprint = _fingerprint(obj)
    if not fingerprint:
        return "unavailable", None

    content_type = _content_type(obj)
    row = ReadAlongTiming.objects.filter(content_type=content_type, object_id=obj.pk).first()
    now = timezone.now()

    if row and row.fingerprint == fingerprint:
        if row.status == ReadAlongTiming.STATUS_READY and not (needs_retry(row) and now - row.updated_at >= RETRY_FAILED_AFTER):
            return "ready", row
        if row.status == ReadAlongTiming.STATUS_WORKING and now - row.updated_at < WORKING_FOR:
            # Whatever is known so far — usually where the voice speaks —
            # so the page can follow the reading while it waits.
            return "pending", row
        if row.status == ReadAlongTiming.STATUS_FAILED and now - row.updated_at < RETRY_FAILED_AFTER:
            return "unavailable", None

    if not start or not is_configured() or _self_timed(obj):
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


def measure_when_saved(sender, instance, raw=False, **kwargs):
    """Start measuring as soon as an admin saves a recording, so the words
    are ready before anyone opens the page. Without this the measuring
    only begins when the first learner arrives, and they spend the first
    minute of the lesson without the highlight."""
    from django.conf import settings

    if raw or getattr(settings, "TESTING", False) or not is_configured() or _self_timed(instance):
        return
    try:
        fingerprint = _fingerprint(instance)
        if not fingerprint:
            return
        from .models import ReadAlongTiming

        content_type = _content_type(instance)
        row = ReadAlongTiming.objects.filter(content_type=content_type, object_id=instance.pk).first()
        if row and row.fingerprint == fingerprint and row.status != ReadAlongTiming.STATUS_FAILED:
            return                     # already measured, or being measured now
        _queue(instance)
    except Exception:                  # a timing must never break saving
        logger.exception("Couldn't start measuring %s %s", instance.__class__.__name__, instance.pk)


def read_along_models():
    """Every model whose recordings the words follow."""
    from django.apps import apps as django_apps

    for label in TEXT_FOR:
        try:
            yield django_apps.get_model(label)
        except LookupError:
            continue


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

    if _self_timed(obj):
        # Read aloud here, with its timings from the voice: nothing to measure.
        return ReadAlongTiming.objects.filter(content_type=_content_type(obj), object_id=obj.pk).first()
    fingerprint = _fingerprint(obj)
    content_type = _content_type(obj)
    row, _created = ReadAlongTiming.objects.get_or_create(
        content_type=content_type, object_id=obj.pk, defaults={"fingerprint": fingerprint}
    )
    if not fingerprint:
        row.delete()
        return None
    if row.engine == MANUAL and row.fingerprint in (fingerprint, _fingerprint(obj, VERSION)):
        # Timed by hand for this very recording and text: never guessed over.
        if row.fingerprint != fingerprint:
            row.fingerprint = fingerprint
            row.save(update_fields=["fingerprint", "updated_at"])
        return row

    text = text_for(obj)
    _identity, source = _media(obj)
    errors = []
    words, engine, runs, length = None, "", [], None
    list_quality = None
    try:
        with tempfile.TemporaryDirectory(prefix="read-along-") as folder:
            audio = _extract_audio(source, folder)
            length = _duration(audio)
            runs = speech_runs(audio, length)
            # Saved before the transcribing begins, which takes far longer:
            # knowing when the voice speaks and pauses is enough for the
            # page to follow the reading sensibly while it waits for the
            # word-by-word timings.
            if runs:
                ReadAlongTiming.objects.filter(pk=row.pk).update(speech=runs, duration=length, updated_at=timezone.now())
            is_list = _label(obj) in TAP_ALONG
            # Forced alignment makes the text fit the recording; a spelling
            # lesson says far more than its list, so lists are transcribed.
            if (getattr(settings, "ELEVENLABS_API_KEY", "") and not (is_list and getattr(settings, "OPENAI_API_KEY", ""))
                    and not cache.get(NO_FORCED_ALIGNMENT)):
                try:
                    words, engine = _elevenlabs(audio, text), "elevenlabs"
                except AlignmentUnavailable as error:
                    errors.append(str(error))
                    if "missing the permission" in str(error) or "missing_permissions" in str(error):
                        # The key can't align: don't upload every recording just to hear that again.
                        cache.set(NO_FORCED_ALIGNMENT, True, 6 * 60 * 60)
            if words is None and getattr(settings, "ELEVENLABS_API_KEY", "") and not is_list:
                # ElevenLabs Scribe: precise word times (a long recording in pieces).
                try:
                    if _too_long_for_one_go(audio, length):
                        words = _transcribe_long(audio, text, runs, length, folder, engine=_scribe)
                    else:
                        words = _scribe(audio)
                    engine = "scribe"
                except AlignmentUnavailable as error:
                    errors.append(str(error))
                    words = None
            if words is None and getattr(settings, "OPENAI_API_KEY", "") and _too_long_for_one_go(audio, length):
                # A long recording (a whole book read aloud, say) is heard
                # in pieces, cut in its pauses, and put back together.
                try:
                    words, engine = _transcribe_long(audio, text, runs, length, folder), "openai"
                    words = even_out(_recover_dropped(audio, words, runs, folder, limit=40))
                except AlignmentUnavailable as error:
                    errors.append(str(error))
            if words is None and getattr(settings, "OPENAI_API_KEY", ""):
                # Told what it should hear, Whisper comes back with the
                # page's own wording — but the hint can also make it skip a
                # sentence it thinks it already has. So listen both ways
                # and keep whichever follows the page more closely.
                heard = []
                for hint in (text, ""):
                    try:
                        heard.append(_transcribe(audio, hint=hint))
                    except AlignmentUnavailable as error:
                        errors.append(str(error))
                heard = [attempt for attempt in heard if attempt]
                if heard:
                    words = max(heard, key=lambda attempt: (_spoken_share(text, attempt), len(attempt)))
                    engine = "openai"
                if words:
                    words = even_out(_recover_dropped(audio, words, runs, folder))
                if words and is_list:
                    # Each item placed on its own, from every transcript heard.
                    items = tap_items(obj)
                    starts, placed = list_timing(items, heard + [words], runs)
                    words = _item_words(items, starts, length)
                    list_quality = placed / len(items) if items else 0.0
    except AlignmentUnavailable as error:
        errors.append(str(error))

    row.fingerprint = fingerprint
    row.speech = runs
    row.duration = length
    if words:
        row.status, row.engine, row.words, row.error = ReadAlongTiming.STATUS_READY, engine, words, ""
        row.quality = list_quality if list_quality is not None else _spoken_share(text, words)
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


def _download(source, folder):
    """A recording in cloud storage, copied here first. Read straight off
    the network, ffmpeg asks for it a little at a time and a long recording
    (a whole book read aloud) can take longer than it's allowed; a plain
    download of the same file takes a minute or two."""
    import urllib.request

    name = source.split("?", 1)[0].rsplit("/", 1)[-1]
    path = f"{folder}/source.{name.rsplit('.', 1)[-1][:5] if '.' in name else 'media'}"
    import http.client

    try:
        with urllib.request.urlopen(source, timeout=120) as response, open(path, "wb") as out:
            expected = int(response.headers.get("Content-Length") or 0)
            shutil.copyfileobj(response, out, 1024 * 1024)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise AlignmentUnavailable(f"Couldn't fetch the recording: {error}") from error
    # A connection that drops part-way must never pass for the whole recording.
    if expected and os.path.getsize(path) != expected:
        raise AlignmentUnavailable("The recording only partly downloaded; it will be tried again.")
    return path


def _extract_audio(source, folder):
    """A small mono MP3 of the soundtrack — quick to upload, and well
    inside every service's size limit even for a long chapter."""
    if not shutil.which("ffmpeg"):
        raise AlignmentUnavailable("ffmpeg isn't installed.")
    if source.startswith(("http://", "https://")):
        source = _download(source, folder)
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
    # The copy must be the whole recording: timings for only its opening
    # minutes would leave the highlight stuck once those run out.
    try:
        whole, copied = _duration(source), _duration(out)
    except AlignmentUnavailable:
        whole = copied = None
    if whole and copied and copied < whole * 0.85:     # (some MP3s only estimate their length)
        raise AlignmentUnavailable(
            f"Only {copied / 60:.0f} of the recording's {whole / 60:.0f} minutes could be read; it will be tried again.")
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


# ---------------------------------------------------------------------------
# Timing the page's own words
# ---------------------------------------------------------------------------

PAGE_TIMED = {"diction_library.librarychapter"}   # long texts read from an uploaded recording


def page_timed(text, heard):
    """[[page word, start, end], …]: the page's own words, in order, each
    with the time it's said — lined up with what was heard across the
    whole text at once. On a long book, matching a little at a time in the
    page can lose its place and leave a stretch unlit; done here, every
    word the reader says gets its moment. A page word the reader doesn't
    say (a page header, a stage direction skipped) gets none, so it's
    passed over rather than lit at the wrong time."""
    import difflib

    page = text.split()
    if not page or not heard:
        return []
    page_keys = [_key(word) for word in page]
    heard_keys = [_key(word[0]) for word in heard]
    out = []

    def spread(words, start, end):
        if end <= start:
            end = start + 0.05 * len(words)
        weights = [_syllables(word) + 0.4 for word in words]
        total, at = sum(weights), start
        for word, weight in zip(words, weights):
            share = (end - start) * weight / total
            out.append([word, round(at, 3), round(at + share, 3)])
            at += share

    matcher = difflib.SequenceMatcher(None, page_keys, heard_keys)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend([page[i], heard[j][1], heard[j][2]] for i, j in zip(range(i1, i2), range(j1, j2)))
        elif tag == "replace":
            if i2 - i1 == j2 - j1:                     # said a little differently ("Omego" heard as "Omega")
                out.extend([page[i], heard[j][1], heard[j][2]] for i, j in zip(range(i1, i2), range(j1, j2)))
            elif (i2 - i1) <= 3 * (j2 - j1) + 3:
                spread(page[i1:i2], heard[j1][1], heard[j2 - 1][2])
            # far more on the page than was said there: not read aloud
        elif tag == "delete" and i2 - i1 <= 3 and out and j1 < len(heard):
            # A word or two the transcript dropped, between two that were
            # heard: said in the gap, if there is one.
            gap_start, gap_end = out[-1][2], heard[j1][1]
            if gap_end - gap_start >= 0.12:
                spread(page[i1:i2], gap_start, gap_end)
    return _clean(out)


def served_words(obj, row):
    """The word timings the page is sent: for a long text read from an
    uploaded recording, the page's own words already lined up (page_timed),
    worked out once per measurement and kept."""
    if not row or not row.words or _label(obj) not in PAGE_TIMED or row.engine not in ("scribe", "openai"):
        return row.words if row else []
    key = f"read-along:page:{row.pk}:{row.updated_at.timestamp() if row.updated_at else 0}"
    words = cache.get(key)
    if words is None:
        words = page_timed(text_for(obj), row.words) or row.words
        cache.set(key, words, 24 * 60 * 60)
    return words


def _voice_without_words(runs, words):
    """Stretches where the silence map hears a voice but the transcript has
    no words in it. Whisper sometimes drops a whole passage of a longer
    recording without a trace; this is where to look for it."""
    spans = []
    for start, end in runs or []:
        if spans and start - spans[-1][1] < 0.6:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    # No word takes more than a couple of seconds to say. When Whisper skips
    # a passage it often stretches the next word right over it ("Wow!" from
    # 76s to 90s), hiding the gap — so a stretched word vouches for nothing.
    heard = [(float(word[1]), float(word[2])) for word in words or []
             if float(word[2]) - float(word[1]) <= WORD_MAX]
    missing = []
    for start, end in spans:
        pieces = [[start, end]]
        for word_start, word_end in heard:
            kept = []
            for piece_start, piece_end in pieces:
                if word_end <= piece_start or word_start >= piece_end:
                    kept.append([piece_start, piece_end])
                    continue
                if word_start > piece_start:
                    kept.append([piece_start, word_start])
                if word_end < piece_end:
                    kept.append([word_end, piece_end])
            pieces = kept
        missing += [piece for piece in pieces if piece[1] - piece[0] >= DROPPED_VOICE]
    return missing


# ---------------------------------------------------------------------------
# Long recordings: heard in pieces
# ---------------------------------------------------------------------------

PIECE_SECONDS = 10 * 60      # each piece about this long: far inside Whisper's 25 MB
LONG_SECONDS = 20 * 60       # anything longer than this is heard in pieces
PIECES_AT_ONCE = 4

_COMMON = set("""the a an and but or of to in on at for with from by as is was were be been are am it its this that
these those he she they we you i me him her them us my your his our their there here what when where who why how
not no yes so if then than too very all any some one two three said says say will would can could shall should may
might must do does did done have has had just now up down out over into about after before again also only well oh
mr mrs miss sir madam enter exit scene act""".split())


def _too_long_for_one_go(audio, length):
    return (length or 0) > LONG_SECONDS or os.path.getsize(audio) > OPENAI_MAX_BYTES * 0.8


def _cut_points(runs, length):
    """Where to cut a long recording: about every PIECE_SECONDS, each time
    in the middle of the pause nearest that moment, so no word is split."""
    gaps = [(runs[i][1] + runs[i + 1][0]) / 2 for i in range(len(runs) - 1)
            if runs[i + 1][0] - runs[i][1] >= 0.3]
    cuts, target = [0.0], PIECE_SECONDS
    while target < length - 60:
        near = [g for g in gaps if abs(g - target) <= 45]
        cut = min(near, key=lambda g: abs(g - target)) if near else target
        if cut > cuts[-1] + 60:
            cuts.append(cut)
        target = cuts[-1] + PIECE_SECONDS
    cuts.append(length)
    return list(zip(cuts, cuts[1:]))


def _names_hint(text, share_from, share_to):
    """Whisper's hint for one piece: the names and unusual words from the
    part of the text that piece most likely reads (with some to spare),
    so "Nduka" or "Ibekwe" are written as the book writes them."""
    words = text.split()
    if not words:
        return ""
    lo = max(0, int(len(words) * share_from) - 400)
    hi = min(len(words), int(len(words) * share_to) + 400)
    seen, chosen = set(), []
    for raw in words[lo:hi]:
        word = re.sub(r"[^\w'’-]", "", raw)
        key = word.lower()
        if len(word) < 3 or key in _COMMON or key in seen:
            continue
        if word[0].isupper() or len(word) >= 9:
            seen.add(key)
            chosen.append(word)
    return ", ".join(chosen)


def _transcribe_long(audio, text, runs, length, folder, engine=None):
    """Every word of a long recording, with times in the whole recording."""
    engine = engine or _transcribe
    from concurrent.futures import ThreadPoolExecutor

    pieces = _cut_points(runs, length)

    def hear(numbered):
        n, (start, end) = numbered
        clip = f"{folder}/piece-{n:03d}.mp3"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
             "-i", audio, "-ac", "1", "-ar", "16000", "-b:a", "32k", clip],
            capture_output=True, timeout=EXTRACT_TIMEOUT, check=True,
        )
        hint = _names_hint(text, start / length, end / length)
        try:
            found = engine(clip, hint=hint)
        except AlignmentUnavailable:
            found = engine(clip, hint="")               # once more, on its own
        return [[word, round(a + start, 3), round(b + start, 3)] for word, a, b in found]

    with ThreadPoolExecutor(max_workers=PIECES_AT_ONCE) as pool:
        results = list(pool.map(lambda item: _safe(hear, item), enumerate(pieces)))
    heard = [word for piece in results if piece for word in piece]
    missing = sum(1 for piece in results if not piece)
    if not heard:
        raise AlignmentUnavailable("None of the recording's pieces could be transcribed.")
    if missing:
        logger.warning("Read-along: %d of %d pieces of a long recording couldn't be transcribed.", missing, len(pieces))
    logger.info("Read-along: a %.0f-minute recording was heard in %d pieces, %d words.", length / 60, len(pieces), len(heard))
    return _clean(heard)


def _safe(hear, item):
    try:
        return hear(item)
    except (AlignmentUnavailable, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        logger.warning("Read-along: piece %s couldn't be transcribed: %s", item[0], error)
        return []


def _recover_dropped(audio, words, runs, folder, limit=None):
    """Transcribe again, on its own, each stretch of voice the first pass
    skipped, and let what it hears there replace what the first pass said.
    With `limit`, only the longest that many stretches (a long book has
    many short ones, and each is a request of its own)."""
    words = [list(word) for word in words]
    recovered = 0
    gaps = _voice_without_words(runs, words)
    if limit is not None and len(gaps) > limit:
        gaps = sorted(sorted(gaps, key=lambda gap: gap[1] - gap[0], reverse=True)[:limit])
    for start, end in gaps:
        begin = max(0.0, start - GAP_PAD)
        clip = f"{folder}/gap-{int(begin * 1000)}.mp3"
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{begin:.3f}",
                 "-t", f"{(end - begin) + GAP_PAD:.3f}", "-i", audio, clip],
                capture_output=True, timeout=EXTRACT_TIMEOUT, check=True,
            )
            # No hint here: on a short clip it could be echoed back as words.
            found = _transcribe(clip, hint="")
        except (AlignmentUnavailable, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
        found = [[text, round(word_start + begin, 3), round(word_end + begin, 3)]
                 for text, word_start, word_end in found]
        # The first pass's words in the gap are the ones it got wrong: a
        # word stretched over it, or a stray. The clip's own words go there
        # instead, unless they only repeat a neighbour at the clip's edge.
        within = lambda word: begin <= word[1] < end
        kept = [word for word in words if not within(word)]
        fresh = [word for word in found
                 if within(word)
                 and not any(_key(other[0]) == _key(word[0]) and abs(other[1] - word[1]) < 0.3 for other in kept)]
        if len(fresh) <= len(words) - len(kept):
            continue
        recovered += len(fresh) - (len(words) - len(kept))
        words = sorted(kept + fresh, key=lambda word: word[1])
    if not recovered:
        return words

    # Anything still stretched is said once, at its start.
    words = [[text, word_start, min(word_end, round(word_start + WORD_MAX, 3))] for text, word_start, word_end in words]
    logger.info("Read-along: recovered %d word(s) the first transcription dropped.", recovered)
    return _clean(words)


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


# Connections to the services are kept open between calls (_http — not to
# be confused with _pool above, which runs measurements in the background). Setting one up again costs as
# much as half a second, which the reading tutor waits on while a learner
# sits there — so the same connection is reused for every request.
try:
    import urllib3

    _http = urllib3.PoolManager(
        maxsize=8, retries=False,
        timeout=urllib3.Timeout(connect=15, read=API_TIMEOUT),
        headers={"User-Agent": "dictionmasters/1.0"},
    )
except Exception:            # pragma: no cover - urllib3 comes with boto3
    _http = None


def _post(url, headers, body, content_type, service):
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={**headers, "Content-Type": content_type, "Accept": "application/json", "User-Agent": "dictionmasters/1.0"},
    )
    for attempt in range(RATE_LIMIT_TRIES):
        try:
            if _http is not None:
                answer = _http.request("POST", url, body=body, headers=dict(request.headers))
                if answer.status == 429 and attempt + 1 < RATE_LIMIT_TRIES:
                    _wait(answer.headers.get("Retry-After"), attempt)
                    continue
                if answer.status >= 400:
                    raise AlignmentUnavailable(
                        f"{service} answered HTTP {answer.status}: {answer.data[:200].decode('utf-8', errors='ignore')}")
                return json.loads(answer.data.decode("utf-8"))
            with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt + 1 < RATE_LIMIT_TRIES:
                _wait(error.headers.get("Retry-After"), attempt)
                continue
            detail = error.read()[:200].decode("utf-8", errors="ignore")
            raise AlignmentUnavailable(f"{service} answered HTTP {error.code}: {detail}") from error
        except AlignmentUnavailable:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            raise AlignmentUnavailable(f"Couldn't reach {service}.") from error
        except Exception as error:      # urllib3's own troubles
            raise AlignmentUnavailable(f"Couldn't reach {service}.") from error


def _wait(retry_after, attempt):
    """Told to slow down: wait as long as it asks, within reason."""
    try:
        asked = float(retry_after or 0)
    except (TypeError, ValueError):
        asked = 0
    time.sleep(min(max(asked, 5.0 * (attempt + 1)), 60.0))


def _clean(words):
    """[[word, start, end], …] with blanks dropped and times kept in order."""
    cleaned = []
    last, last_end = 0.0, 0.0
    for text, start, end in words:
        text = str(text or "").strip()
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if not text or start != start or end != end:     # NaN check
            continue
        start = max(start, last)
        # Two words aren't said at once: one that starts inside the word
        # before it (Whisper's "mother." 3.86–4.36, "She" 3.86–4.66) really
        # starts where that one ends.
        if start < last_end < end:
            start = last_end
        end = max(end, start)
        cleaned.append([text, round(start, 3), round(end, 3)])
        last, last_end = start, end
    return cleaned


def _elevenlabs(audio_path, text):
    body, content_type, _size = _multipart([("text", text)], "file", audio_path)
    data = _post(ELEVENLABS_URL, {"xi-api-key": settings.ELEVENLABS_API_KEY}, body, content_type, "ElevenLabs")
    words = _clean((w.get("text"), w.get("start"), w.get("end")) for w in data.get("words") or [])
    if not words:
        raise AlignmentUnavailable("ElevenLabs returned no words.")
    return words


SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
NO_FORCED_ALIGNMENT = "read-along:no-forced-alignment"


def _scribe(audio_path, hint=""):
    """ElevenLabs Scribe: every word heard, with a precise start and end.
    Its word times are far steadier than Whisper's, which often gives a
    word no length at all and hands its time to the word before; that is
    what put the highlight a word ahead. (`hint` is accepted for the same
    shape as _transcribe, but Scribe doesn't need one.)"""
    fields = [("model_id", getattr(settings, "READ_ALONG_SCRIBE_MODEL", "scribe_v1")),
              ("timestamps_granularity", "word"), ("language_code", "eng"), ("tag_audio_events", "false")]
    body, content_type, _size = _multipart(fields, "file", audio_path)
    data = _post(SCRIBE_URL, {"xi-api-key": settings.ELEVENLABS_API_KEY}, body, content_type, "ElevenLabs Scribe")
    words = _clean((w.get("text"), w.get("start"), w.get("end"))
                   for w in data.get("words") or [] if w.get("type", "word") == "word")
    if not words:
        raise AlignmentUnavailable("ElevenLabs Scribe returned no words.")
    return words


def _syllables(word):
    return max(1, len(re.findall(r"[aeiouy]+", word.lower())))


def even_out(words):
    """Repair word times that can't be right: a word with no length, or a
    one-letter word given far longer than a long word beside it. Each run
    of words said without a pause shares its time out again by how long
    each word takes to say, so the highlight lands on the word being said."""
    words = [list(w) for w in words]
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1][1] - words[j][2] < 0.05:
            j += 1
        group = words[i:j + 1]
        span_start, span_end = group[0][1], group[-1][2]

        def odd(word):
            length = word[2] - word[1]
            per = length / _syllables(word[0])
            return length < 0.06 or per > 0.9 or (len(word[0]) <= 2 and length > 0.5)

        if len(group) > 1 and span_end > span_start and any(odd(w) for w in group):
            weights = [_syllables(w[0]) + 0.4 for w in group]
            total, at = sum(weights), span_start
            for word, weight in zip(group, weights):
                share = (span_end - span_start) * weight / total
                word[1], word[2] = round(at, 3), round(at + share, 3)
                at += share
        i = j + 1
    return words


def _transcribe(audio_path, hint=""):
    """OpenAI's Whisper, with a time for every word it hears."""
    fields = [
        ("model", settings.OPENAI_TRANSCRIBE_MODEL),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("language", "en"),
        ("temperature", "0"),
    ]
    if hint:
        # Whisper listens for these words in particular. The opening of
        # the text is sent, cut at a word so the last one isn't half a word.
        opening = " ".join(hint.split())[:OPENAI_PROMPT_LIMIT]
        if len(opening) == OPENAI_PROMPT_LIMIT and " " in opening:
            opening = opening.rsplit(" ", 1)[0]
        fields.append(("prompt", opening))
    body, content_type, size = _multipart(fields, "file", audio_path)
    if size > OPENAI_MAX_BYTES:
        raise AlignmentUnavailable("The recording is too long to transcribe.")
    data = _post(OPENAI_URL, {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                 body, content_type, "OpenAI")
    words = _clean((w.get("word"), w.get("start"), w.get("end")) for w in data.get("words") or [])
    if not words:
        raise AlignmentUnavailable("OpenAI returned no words.")
    return words


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------

def candidates(only=None):
    """Every object that has text and a recording to read along with —
    or, with `only` (app labels such as "diction_library"), just those."""
    from django.apps import apps
    from django.db.models import Q

    for label in TEXT_FOR:
        if only and label.split(".")[0] not in only:
            continue
        model = apps.get_model(label)
        names = {f.name for f in model._meta.fields}
        has_media = Q()
        for pair in _media_fields(model):
            for field in pair:
                if field in names:
                    has_media |= ~Q(**{field: ""})
        for obj in model.objects.filter(has_media):
            if _fingerprint(obj):
                yield obj
