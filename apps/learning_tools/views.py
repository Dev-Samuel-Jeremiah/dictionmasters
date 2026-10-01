import csv
import io
import json
import logging
import re
import shutil
import subprocess
import time

from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.quick_words.speech import SpeechUnavailable, is_configured as speech_is_configured, speak

logger = logging.getLogger(__name__)

BOOK_SCAN_CHUNK_CHARS = 4000
BOOK_SCAN_HOURLY_CHARS = 48000
BOOK_SCAN_AUDIO_MAX_BYTES = 8 * 1024 * 1024
BOOK_SCAN_AUDIO_TIMEOUT_SECONDS = 60
BOOK_SCAN_IMAGE_MAX_BYTES = 15 * 1024 * 1024
BOOK_SCAN_IMAGE_MAX_PIXELS = 50_000_000


def _book_scan_audio_quota(user, characters):
    """Keep generated narration within a per-account hourly character budget."""
    hour = int(time.time() // 3600)
    key = f"book-scan-audio:{user.pk}:{hour}"
    if cache.add(key, characters, timeout=3700):
        return characters <= BOOK_SCAN_HOURLY_CHARS
    try:
        total = cache.incr(key, characters)
    except ValueError:
        # The key may expire between add() and incr() at an hour boundary.
        return cache.add(key, characters, timeout=3700) and characters <= BOOK_SCAN_HOURLY_CHARS
    return total <= BOOK_SCAN_HOURLY_CHARS

TOOLS = [
    {
        "name": "AI Reading Tutor",
        "blurb": "Read a passage aloud to a live tutor. It stops to help with any word you mispronounce, then gives you your reading level and feedback straight away.",
        "url_name": "tutor:hub", "available": True, "icon": "tutor",
    },
    {
        "name": "Scan & Listen",
        "blurb": "Photograph a page from any book, turn it into editable text, and listen as it is read aloud.",
        "url_name": "learning_tools:book_scanner", "available": True, "icon": "scan",
    },
    {
        "name": "Daily Practice",
        "blurb": "A fresh set of pronunciation drills — a word, a sentence and a tongue twister — pulled at random from the 44 Academy each day.",
        "url_name": "daily_practice:home", "available": True, "icon": "daily-practice",
    },
    {
        "name": "44 Academy",
        "blurb": "A full lesson for every sound of English: articulation, word bank, sentence practice, passages, conversations, twisters and minimal pairs.",
        "url_name": "book:home", "available": True, "icon": "book",
    },
    {
        "name": "Tricks to Sound Fluent",
        "blurb": "The tricks that make English flow, each a full lesson: the trick, a word list, sentence practice, passages, conversations, twisters and minimal pairs.",
        "url_name": "tricks:home", "available": True, "icon": "tricks",
    },
    {
        "name": "Reading Club",
        "blurb": "This term's reading book, chapter by chapter — listen to the model reading, follow the text, and work through First, Second and Third term in order.",
        "url_name": "reading_club:hub", "available": True, "icon": "reading-club",
    },
    {
        "name": "Reference Library",
        "blurb": "Look things up — grammar points, spelling rules, word origins and anything else worth researching, browsable by topic or searchable by keyword.",
        "url_name": "reference_library:home", "available": True,
    },
    {
        "name": "Diction Library",
        "blurb": "Books, stories, audio and video shared by Diction Masters and your school.",
        "url_name": "diction_library:hub", "available": True, "icon": "diction-library",
    },
    {
        "name": "Diction Radio",
        "blurb": "Tune in to pronunciation, storytelling and language programmes, played one after another.",
        "url_name": "diction_radio:home", "available": True, "icon": "diction-radio",
    },
]


@login_required
def hub(request):
    """The launcher for every learning tool. New tools join this list
    as they're built, each as its own app."""
    return render(request, "learning_tools/hub.html", {"tools": TOOLS})


@login_required
def book_scanner(request):
    """A private, in-browser book scanner and read-aloud workspace."""
    return render(request, "learning_tools/book_scanner.html", {
        "narration_configured": speech_is_configured(),
    })


def _read_tesseract_tsv(tsv):
    """Restore Tesseract's word boxes into paragraphs and a rough confidence."""
    paragraphs = OrderedDict()
    confidences = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = (row.get("block_num", "0"), row.get("par_num", "0"))
        line = row.get("line_num", "0")
        paragraphs.setdefault(key, OrderedDict()).setdefault(line, []).append(word)
        try:
            confidence = float(row.get("conf", "-1"))
            if confidence >= 0:
                confidences.append(confidence)
        except (TypeError, ValueError):
            pass
    text = "\n\n".join(
        "\n".join(" ".join(words) for words in lines.values())
        for lines in paragraphs.values()
    ).strip()
    confidence = round(sum(confidences) / len(confidences)) if confidences else 0
    return text, confidence


@login_required
@require_POST
def book_scanner_recognize(request):
    """OCR one compressed page with the server's installed Tesseract binary.

    The image is passed to Tesseract on stdin and is never written to storage.
    """
    uploaded = request.FILES.get("image")
    if uploaded is None:
        return JsonResponse({"error": "Choose a page photo to scan."}, status=400)
    if uploaded.size > BOOK_SCAN_IMAGE_MAX_BYTES:
        return JsonResponse({"error": "This photo is larger than 15 MB. Choose a smaller page photo."}, status=413)
    if not shutil.which("tesseract"):
        return JsonResponse({"error": "Page recognition is temporarily unavailable. Please contact your administrator."}, status=503)

    try:
        with Image.open(uploaded) as original:
            if original.width * original.height > BOOK_SCAN_IMAGE_MAX_PIXELS:
                return JsonResponse({"error": "This photo is too large to process. Choose a smaller page image."}, status=413)
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
            image = ImageOps.autocontrast(ImageOps.grayscale(image))
            prepared = io.BytesIO()
            image.save(prepared, format="JPEG", quality=92, optimize=True)
            page_bytes = prepared.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return JsonResponse({"error": "This image could not be opened. Choose a clear JPG, PNG or WebP photo."}, status=400)

    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--oem", "1", "--psm", "3", "tsv"],
            input=page_bytes, capture_output=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        return JsonResponse({"error": "This page took too long to read. Try a sharper photo of one page."}, status=504)
    except OSError:
        logger.exception("Tesseract could not start for Scan & Listen user %s", request.user.pk)
        return JsonResponse({"error": "Page recognition is temporarily unavailable. Please try again shortly."}, status=503)
    if result.returncode:
        logger.warning("Tesseract returned an error for Scan & Listen user %s", request.user.pk)
        return JsonResponse({"error": "This page could not be read. Try a sharper photo in better light."}, status=422)

    text, confidence = _read_tesseract_tsv(result.stdout.decode("utf-8", errors="replace"))
    return JsonResponse({"text": text, "confidence": confidence})


@login_required
@require_POST
def book_scanner_narrate(request):
    """Turn one short transcript segment into MP3 with the configured
    ElevenLabs voice. The transcript and audio are never stored here."""
    if not speech_is_configured():
        return JsonResponse({"error": "Diction Masters narration is not configured yet."}, status=503)
    try:
        content_length = int(request.META.get("CONTENT_LENGTH", "0"))
    except (TypeError, ValueError):
        content_length = 0
    if content_length > (BOOK_SCAN_CHUNK_CHARS * 4) + 2000:
        return JsonResponse({"error": "This text segment is too large."}, status=413)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The narration request was not valid."}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return JsonResponse({"error": "Add text before requesting narration."}, status=400)

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", payload["text"]).strip()
    if not text:
        return JsonResponse({"error": "Add text before requesting narration."}, status=400)
    if len(text) > BOOK_SCAN_CHUNK_CHARS:
        return JsonResponse({"error": "This text segment is too large. Please try again."}, status=413)
    if not _book_scan_audio_quota(request.user, len(text)):
        return JsonResponse({
            "error": "The Scan & Listen narration allowance for this account has been reached for this hour. Please try again later."
        }, status=429)

    try:
        audio = speak(
            text,
            model_id=settings.BOOK_SCAN_VOICE_MODEL_ID,
            max_audio_bytes=BOOK_SCAN_AUDIO_MAX_BYTES,
            timeout_seconds=BOOK_SCAN_AUDIO_TIMEOUT_SECONDS,
        )
    except SpeechUnavailable as exc:
        logger.warning("Scan & Listen narration failed for user %s: %s", request.user.pk, exc)
        return JsonResponse({"error": "Narration is temporarily unavailable. Please try again shortly."}, status=503)

    response = HttpResponse(audio, content_type="audio/mpeg")
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response
