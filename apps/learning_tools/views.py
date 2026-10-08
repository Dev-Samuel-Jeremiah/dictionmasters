import csv
import io
import json
import logging
import shutil
import subprocess

from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.diction_library.narration import voice_configured

from . import page_reader, scan_library
from .models import ScanReading

logger = logging.getLogger(__name__)

BOOK_SCAN_IMAGE_MAX_BYTES = 15 * 1024 * 1024
BOOK_SCAN_IMAGE_MAX_PIXELS = 50_000_000


# Every course and tool on the Learn page, once each, in the order shown.
# Site search (apps/platform_search) looks through this list too, so every
# entry must have a working url_name. `section` picks the Learn page's
# heading; `icon` and `tone` are the icon include's name and a theme.css
# tint, and `image` a picture used instead of the icon. `teachers` hides
# a tool from students.
SECTIONS = [
    ("courses", "Courses"),
    ("practise", "Practise and play"),
    ("read", "Read, listen and look up"),
    ("teachers", "For teachers"),
]

TOOLS = [
    {
        "name": "44 Academy",
        "blurb": "A full lesson for every sound of English: articulation, word bank, sentence practice, passages, conversations, twisters and minimal pairs.",
        "url_name": "book:home", "available": True, "section": "courses", "icon": "cap", "tone": "t-butter", "image": "img/app/c44.jpg",
    },
    {
        "name": "EchoSpell",
        "blurb": "Spelling and phonics by level, with scored activities.",
        "url_name": "echospell:hub", "available": True, "section": "courses", "icon": "abc", "tone": "t-sky", "image": "img/app/cEcho.jpg",
    },
    {
        "name": "Tricks to Sound Fluent",
        "blurb": "The tricks that make English flow, each a full lesson: the trick, a word list, sentence practice, passages, conversations, twisters and minimal pairs.",
        "url_name": "tricks:home", "available": True, "section": "courses", "icon": "spark", "tone": "t-blush", "image": "img/app/cSB.jpg",
    },
    {
        "name": "Learning Modules",
        "blurb": "Term by term, week by week, Monday to Friday.",
        "url_name": "learning_modules:hub", "available": True, "section": "courses", "icon": "book", "tone": "t-mint", "image": "img/app/cSchool.jpg",
    },
    {
        "name": "Reading Club",
        "blurb": "This term's reading book, chapter by chapter — listen to the model reading, follow the text, and work through First, Second and Third term in order.",
        "url_name": "reading_club:hub", "available": True, "section": "courses", "icon": "shelf", "tone": "t-lilac",
    },
    {
        "name": "Conversational Dialogue",
        "blurb": "A short conversation for every school day, by level.",
        "url_name": "conversational_dialogue:hub", "available": True, "section": "courses", "icon": "mic", "tone": "t-butter", "image": "img/app/practiceGirl.jpg",
    },
    {
        "name": "Assembly Recitals",
        "blurb": "Days, months, numbers and diction songs to say together.",
        "url_name": "assembly_recitals:hub", "available": True, "section": "courses", "icon": "mic", "tone": "t-sky", "image": "img/app/teacher.jpg",
    },
    {
        "name": "Daily Practice",
        "blurb": "A fresh set of pronunciation drills — a word, a sentence and a tongue twister — pulled at random from the 44 Academy each day.",
        "url_name": "daily_practice:home", "available": True, "section": "practise", "icon": "calendar", "tone": "t-mint",
    },
    {
        "name": "Read with Yela",
        "blurb": "Your AI reading tutor: read a passage aloud and it stops to help with any word you mispronounce, then gives you your reading level and feedback straight away.",
        "url_name": "tutor:hub", "available": True, "section": "practise", "icon": "robot", "tone": "t-sky", "image": "img/app/cYala.jpg",
    },
    {
        "name": "Diction Clash",
        "blurb": "Timed games built from your lessons. Fastest correct answers win.",
        "url_name": "clash:hub", "available": True, "section": "practise", "icon": "swords", "tone": "t-blush",
    },
    {
        "name": "Quick Words",
        "blurb": "Hear any word, see its meaning and save it to your lists.",
        "url_name": "quick_words:hub", "available": True, "section": "practise", "icon": "words", "tone": "t-butter",
    },
    {
        "name": "Phonemic chart",
        "blurb": "Every sound of English, with audio.",
        "url_name": "book:phonemic_chart", "available": True, "section": "practise", "icon": "ipa", "tone": "t-sky",
    },
    {
        "name": "Scan & Listen",
        "blurb": "Photograph a page from any book, turn it into editable text, and listen as it is read aloud.",
        "url_name": "learning_tools:book_scanner", "available": True, "section": "read", "icon": "scan", "tone": "t-sky",
    },
    {
        "name": "Diction Library",
        "blurb": "Books, stories, audio and video shared by Diction Masters and your school.",
        "url_name": "diction_library:hub", "available": True, "section": "read", "icon": "shelf", "tone": "t-mint",
    },
    {
        "name": "Diction Radio",
        "blurb": "Tune in to pronunciation, storytelling and language programmes, played one after another.",
        "url_name": "diction_radio:home", "available": True, "section": "read", "icon": "radio", "tone": "t-butter",
    },
    {
        "name": "Reference Library",
        "blurb": "Look things up — grammar points, spelling rules, word origins and anything else worth researching, browsable by topic or searchable by keyword.",
        "url_name": "reference_library:home", "available": True, "section": "read", "icon": "search", "tone": "t-stone",
    },
    {
        "name": "Lesson Notes to Audio",
        "blurb": "For teachers: upload, paste or generate a lesson note, hear it read in a natural British voice, and practise its key words before you teach.",
        "url_name": "lesson_audio:hub", "available": True, "section": "teachers", "icon": "note-audio", "tone": "t-butter", "teachers": True,
    },
]


@login_required
def hub(request):
    """Learn: every course and tool, once each, under a few plain
    headings. New tools join TOOLS as they're built, each as its own app."""
    tools = TOOLS
    if request.user.is_student and not request.user.is_staff:
        tools = [tool for tool in TOOLS if not tool.get("teachers")]
    sections = [
        {"key": key, "title": title, "tools": [tool for tool in tools if tool["section"] == key]}
        for key, title in SECTIONS
    ]
    return render(request, "learning_tools/hub.html", {"sections": [s for s in sections if s["tools"]]})


@login_required
def book_scanner(request):
    """Scan & Listen: snap a page, check the words, listen. ?reading=<id>
    opens a saved reading — the person's own, or one from their school."""
    reading = None
    raw = request.GET.get("reading", "")
    if raw.isdigit():
        reading = scan_library.visible(request.user).filter(pk=int(raw)).select_related("owner", "school").first()
    if reading is not None and reading.has_audio:
        ScanReading.objects.filter(pk=reading.pk).update(plays=F("plays") + 1)
    return render(request, "learning_tools/book_scanner.html", {
        "narration_configured": voice_configured(),
        "reading": reading,
        "is_mine": bool(reading and reading.owner_id == request.user.pk),
        "can_delete": bool(reading and scan_library.may_change(request.user, reading)),
        "audio_status": scan_library.status_of(reading) if reading else "",
        "audio_current": bool(reading and scan_library.audio_is_current(reading)),
        "library_name": request.user.school.name if request.user.school_id else "",
        "recent": scan_library.search(request.user, limit=6),
    })


def _read_tesseract_tsv(tsv):
    """Restore Tesseract's word boxes into paragraphs and a rough confidence."""
    paragraphs = OrderedDict()
    confidences = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
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
    text = page_reader.reflow(
        [[" ".join(words) for words in lines.values()] for lines in paragraphs.values()]
    )
    confidence = round(sum(confidences) / len(confidences)) if confidences else 0
    return text, confidence


def _tesseract(page_bytes):
    """(text, confidence) from the server's Tesseract, or a JsonResponse error."""
    if not shutil.which("tesseract"):
        logger.error("Tesseract OCR is not available on the server handling Scan & Listen")
        return JsonResponse({"error": "Page recognition is temporarily unavailable. Please contact your administrator."}, status=503)
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--oem", "1", "--psm", "3",
             "-c", "preserve_interword_spaces=1", "tsv"],
            input=page_bytes, capture_output=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        return JsonResponse({"error": "This page took too long to read. Try a sharper photo of one page."}, status=504)
    except OSError:
        logger.exception("Tesseract could not start for Scan & Listen")
        return JsonResponse({"error": "Page recognition is temporarily unavailable. Please try again shortly."}, status=503)
    if result.returncode:
        logger.warning("Tesseract returned an error for Scan & Listen")
        return JsonResponse({"error": "This page could not be read. Try a sharper photo in better light."}, status=422)
    return _read_tesseract_tsv(result.stdout.decode("utf-8", errors="replace"))


@login_required
@require_POST
def book_scanner_recognize(request):
    """Read one photographed page into text.

    The AI vision reader (page_reader.py) copies the page word for word; the
    server's Tesseract is the fallback when it isn't configured or fails.
    The image stays in memory and is never written to storage.
    """
    uploaded = request.FILES.get("image")
    if uploaded is None:
        return JsonResponse({"error": "Choose a page photo to scan."}, status=400)
    if uploaded.size > BOOK_SCAN_IMAGE_MAX_BYTES:
        return JsonResponse({"error": "This photo is larger than 15 MB. Choose a smaller page photo."}, status=413)

    try:
        with Image.open(uploaded) as original:
            if original.width * original.height > BOOK_SCAN_IMAGE_MAX_PIXELS:
                return JsonResponse({"error": "This photo is too large to process. Choose a smaller page image."}, status=413)
            image = ImageOps.exif_transpose(original).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return JsonResponse({"error": "This image could not be opened. Choose a clear JPG, PNG or WebP photo."}, status=400)

    if page_reader.ai_configured():
        # The vision model looks at the page at up to 2048px, so a sharp
        # photo at that size gives it every detail it can use.
        for_ai = image.copy()
        for_ai.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        prepared = io.BytesIO()
        for_ai.save(prepared, format="JPEG", quality=90, optimize=True)
        try:
            text = page_reader.read_page(prepared.getvalue())
            return JsonResponse({"text": text, "engine": "ai"})
        except page_reader.PageReadUnavailable as exc:
            logger.warning("Scan & Listen AI page reading failed for user %s, using Tesseract: %s", request.user.pk, exc)

    # Tesseract reads best with text around 30px tall: enlarge a small
    # photo, shrink a huge one, and give it clean grey contrast.
    longest = max(image.size)
    if longest < 1800:
        factor = 1800 / longest
        image = image.resize((round(image.width * factor), round(image.height * factor)), Image.Resampling.LANCZOS)
    image.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
    prepared = io.BytesIO()
    image.save(prepared, format="PNG")
    found = _tesseract(prepared.getvalue())
    if isinstance(found, JsonResponse):
        return found
    text, confidence = found
    return JsonResponse({"text": text, "confidence": confidence, "engine": "ocr"})




# ---------------------------------------------------------------------------
# Saved readings
# ---------------------------------------------------------------------------

def _json_body(request):
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def _reading_state(reading, user):
    return {
        "id": reading.pk,
        "url": reading.get_absolute_url(),
        "title": reading.title,
        "audio": scan_library.status_of(reading),
        "audio_error": reading.audio_error,
        "audio_current": scan_library.audio_is_current(reading),
        "mine": reading.owner_id == user.pk,
        "where": f"{reading.school.name} library" if reading.school_id else "My readings",
    }


@login_required
@require_POST
def reading_save(request):
    """Keep the text as it's scanned or typed (called as it changes)."""
    body = _json_body(request)
    raw_id = body.get("id")
    try:
        reading = scan_library.save(request.user, str(body.get("text") or ""), str(body.get("title") or ""),
                                    int(raw_id) if str(raw_id or "").isdigit() else None)
    except scan_library.ReadingError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse(_reading_state(reading, request.user))


@login_required
@require_POST
def reading_audio(request, pk):
    """Make (or reuse) the read-aloud of a saved reading."""
    reading = get_object_or_404(scan_library.visible(request.user), pk=pk)
    try:
        scan_library.start_audio(reading, request.user)
    except scan_library.ReadingError as error:
        return JsonResponse({"error": str(error)}, status=400)
    reading.refresh_from_db()
    return JsonResponse(_reading_state(reading, request.user))


@login_required
@require_GET
def reading_status(request, pk):
    reading = get_object_or_404(scan_library.visible(request.user), pk=pk)
    response = JsonResponse(_reading_state(reading, request.user))
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def reading_search(request):
    query = request.GET.get("q", "")
    results = scan_library.search(request.user, query)
    return JsonResponse({"results": [{
        "id": r.pk,
        "url": r.get_absolute_url(),
        "title": r.title,
        "snippet": scan_library.snippet(r, query),
        "audio": r.has_audio,
        "by": "You" if r.owner_id == request.user.pk else (r.owner.get_full_name() if r.owner else "Someone at your school"),
        "when": r.updated_at.strftime("%d %b %Y"),
    } for r in results]})


@login_required
@require_POST
def reading_delete(request, pk):
    reading = get_object_or_404(scan_library.visible(request.user), pk=pk)
    if not scan_library.may_change(request.user, reading):
        return JsonResponse({"error": "Only the person who saved it, or your school admin, can delete it."}, status=403)
    scan_library.delete(reading)
    return JsonResponse({"ok": True})
