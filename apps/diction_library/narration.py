"""
Diction Library books, read aloud with the words highlighted.

When a book or story is saved:

1. If it has its own recording (narration_file), that is used: the whole
   main text becomes one chapter, and its word timings are measured like
   any other recording (apps/book/read_along.py).
2. Otherwise the audio is made here, from the book's text, in the site's
   ElevenLabs voice. ElevenLabs sends back the exact moment each letter is
   spoken, so every word's timing comes with the voice — the highlight is
   exact by construction, with nothing to transcribe or guess.

Only the main content is read. The text is taken from the file (PDF, EPUB,
Word .docx or .txt; otherwise the written description), and everything
before the story itself — the title page, the table of contents — is
skipped: the story starts at the first chapter heading that is followed by
real paragraphs (the contents list is headings with nothing under them).
Books without chapter headings start at their first real paragraph.

The book is read a chapter at a time, each chapter its own recording, so a
long book can be listened to (and made) piece by piece. Making it runs in
the background; a chapter already made from the same words is kept, so an
interrupted run carries on where it stopped:

    python manage.py narrate_library            # finish or refresh what's due
    python manage.py narrate_library --dry-run  # what that would make, and its size
"""

import base64
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections

logger = logging.getLogger(__name__)

# Bump to make every book's read-aloud again after a change to how it's done.
VERSION = "1"

CHUNK_CHARS = 2400            # sent to the voice at a time (well inside its limit)
PART_CHARS = 6000             # a book with no chapters is read in parts of about this size
CONTEXT_CHARS = 300           # the words either side, so each piece sounds continuous
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
TIMEOUT = 180
TRIES = 4

READ_KINDS = {"book", "story", "other"}

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library-narration")
_queued = set()
_again = set()
_lock = threading.Lock()


class NarrationUnavailable(Exception):
    """The read-aloud couldn't be made this time."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def voice_configured():
    return bool(getattr(settings, "ELEVENLABS_API_KEY", "") and getattr(settings, "ELEVENLABS_VOICE_ID", "")
                and shutil.which("ffmpeg"))


def _model():
    return getattr(settings, "LIBRARY_VOICE_MODEL_ID", "") or getattr(settings, "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")


def _max_chars():
    return int(getattr(settings, "LIBRARY_NARRATION_MAX_CHARS", 300_000))


def auto_for(item):
    """Is this item read aloud automatically when saved? LIBRARY_AUTO_NARRATE:
    "all" (default), "platform" (only the shared library, not school uploads)
    or "off" (only when "Make the read-aloud again" is ticked)."""
    mode = getattr(settings, "LIBRARY_AUTO_NARRATE", "all")
    if mode == "off":
        return False
    if mode == "platform" and item.school_id:
        return False
    return True


# ---------------------------------------------------------------------------
# The book's words
# ---------------------------------------------------------------------------

def _extension(name):
    name = (name or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def _local_copy(field, folder):
    """A path ffmpeg / pdftotext can read, whatever the storage."""
    try:
        return field.path
    except (NotImplementedError, ValueError, AttributeError):
        pass
    path = f"{folder}/source.{_extension(field.name) or 'bin'}"
    with field.open("rb") as src, open(path, "wb") as out:
        shutil.copyfileobj(src, out)
    return path


def _pdf_paragraphs(path, first=None, last=None):
    """The PDF's paragraphs — of the pages first to last, if given."""
    if not shutil.which("pdftotext"):
        raise NarrationUnavailable("pdftotext isn't installed (poppler-utils).")
    pages = ["-f", str(first), "-l", str(last)] if first and last else []
    done = subprocess.run(["pdftotext", "-enc", "UTF-8", *pages, path, "-"], capture_output=True, timeout=300)
    if done.returncode:
        raise NarrationUnavailable("The PDF's text couldn't be read.")
    pages = [page.splitlines() for page in done.stdout.decode("utf-8", errors="replace").split("\f")]
    # Running headers and footers repeat page after page: not part of the story.
    counts = {}
    for lines in pages:
        for line in {l.strip() for l in lines if l.strip()}:
            counts[line] = counts.get(line, 0) + 1
    repeated = {line for line, n in counts.items() if len(pages) >= 6 and n >= max(3, len(pages) * 0.4) and len(line) < 80}
    lines = []
    for page in pages:
        for line in page:
            text = line.strip()
            if not text or text in repeated or re.fullmatch(r"(page\s*)?\d{1,4}(\s*of\s*\d+)?", text, re.I):
                lines.append("")
                continue
            lines.append(text)
    # pdftotext wraps paragraphs at the page width: a line well short of a
    # full one, or a blank, ends a paragraph; a full one runs on.
    # A full line: the typical length of the longest lines (short dialogue
    # lines are common in stories, so an overall average is far too short).
    widths = sorted(len(l) for l in lines if l)
    full = widths[min(len(widths) - 1, int(len(widths) * 0.98))] if widths else 80
    ends_sentence = re.compile(r"[.!?…:;”\"’')]$")
    opens_speech = re.compile(r"^[“\"‘']")
    paragraphs, current = [], []
    for n, line in enumerate(lines):
        if not line:
            if current:
                paragraphs.append(" ".join(current)); current = []
            continue
        if _is_heading(line) and current:
            paragraphs.append(" ".join(current)); current = []
        current.append(line)
        following = next((l for l in lines[n + 1:n + 3] if l), "")
        finished = bool(ends_sentence.search(line))
        if (_is_heading(line) or len(line) < full * 0.6
                or (finished and len(line) < full - 15)                    # a short last line
                or (finished and opens_speech.match(following))):          # someone starts speaking
            paragraphs.append(" ".join(current)); current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _docx_paragraphs(path):
    from docx import Document

    return [p.text.strip() for p in Document(path).paragraphs if p.text.strip()]


def _epub_paragraphs(path):
    from bs4 import BeautifulSoup

    with zipfile.ZipFile(path) as book:
        container = BeautifulSoup(book.read("META-INF/container.xml"), "xml")
        opf_path = container.find("rootfile")["full-path"]
        opf = BeautifulSoup(book.read(opf_path), "xml")
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        items = {i["id"]: i["href"] for i in opf.find_all("item")}
        paragraphs = []
        for ref in opf.find_all("itemref"):
            href = items.get(ref.get("idref"))
            if not href:
                continue
            try:
                page = BeautifulSoup(book.read(base + href), "lxml")
            except KeyError:
                continue
            for block in page.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
                text = " ".join(block.get_text(" ").split())
                if text:
                    paragraphs.append(text)
    return paragraphs


def _text_paragraphs(raw):
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    out = []
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        # A block of short lines (a title, a list) keeps its lines; prose runs on.
        if all(_is_heading(l) or len(l) < 60 for l in lines) and len(lines) > 1:
            out.extend(lines)
        else:
            out.append(" ".join(lines))
    return out


def book_paragraphs(item):
    """Every paragraph of the book's text, in order."""
    from apps.manage.rich_text import plain_text

    paragraphs = []
    if item.file:
        ext = _extension(item.file.name)
        with tempfile.TemporaryDirectory(prefix="library-") as folder:
            if ext in ("pdf", "docx", "epub"):
                path = _local_copy(item.file, folder)
                paragraphs = {"pdf": _pdf_paragraphs, "docx": _docx_paragraphs, "epub": _epub_paragraphs}[ext](path)
            elif ext == "txt":
                with item.file.open("rb") as src:
                    paragraphs = _text_paragraphs(src.read().decode("utf-8", errors="replace"))
    if not paragraphs and item.description:
        paragraphs = _text_paragraphs(plain_text(item.description))
    return [" ".join(p.split()) for p in paragraphs if p and p.strip()]


# ---------------------------------------------------------------------------
# Where the story starts, and its chapters
# ---------------------------------------------------------------------------

_NUMBERS = ("(?:twenty|thirty|forty|fifty)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|"
            "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
            "sixteen|seventeen|eighteen|nineteen|[0-9]{1,3}|[ivxlc]{1,7}")
HEADING = re.compile(rf"^(chapter|part|unit|lesson|story|section|book)\s+({_NUMBERS})\b", re.I)
CONTENTS = re.compile(r"^(table of contents|contents|chapters|index)$", re.I)
ENDING = re.compile(r"^(the end\.?|about the author|acknowledg(e)?ments?|glossary|bibliography|references)\b", re.I)
BODY_MIN = 200                # a heading with at least this much under it starts real content


def _is_heading(text):
    return len(text) <= 120 and bool(HEADING.match(text.strip()))


def main_chapters(paragraphs, title=""):
    """[(chapter title, [paragraphs])] of the main content only: no title
    page, no table of contents, nothing after "The End"."""
    heads = [i for i, p in enumerate(paragraphs) if _is_heading(p)]

    def body_after(i):
        nxt = next((h for h in heads if h > i), len(paragraphs))
        return sum(len(p) for p in paragraphs[i + 1:nxt])

    start = next((h for h in heads if body_after(h) >= BODY_MIN), None)
    if start is None:
        # No chapters: skip a contents list and the title lines before the
        # first real paragraph; keep a short heading just above it.
        after_contents = 0
        for i, p in enumerate(paragraphs[:60]):
            if CONTENTS.match(p.strip()):
                after_contents = i + 1
        start = next((i for i in range(after_contents, len(paragraphs)) if len(paragraphs[i]) >= 120), after_contents)
        if start > after_contents and len(paragraphs[start - 1]) <= 80 and paragraphs[start - 1].strip().lower() != (title or "").strip().lower():
            start -= 1
    body = paragraphs[start:]
    end = next((i for i, p in enumerate(body) if ENDING.match(p.strip())), None)
    if end is not None:
        keep_end = body[end].strip().lower().startswith("the end")
        body = body[:end + (1 if keep_end else 0)]

    chapters = []
    if any(_is_heading(p) for p in body):
        for p in body:
            if _is_heading(p) or not chapters:
                chapters.append((p if _is_heading(p) else (title or "Beginning"), [p]))
            else:
                chapters[-1][1].append(p)
    else:
        # Parts of about PART_CHARS, at paragraph boundaries.
        part = []
        for p in body:
            part.append(p)
            if sum(len(x) for x in part) >= PART_CHARS:
                chapters.append((f"Part {len(chapters) + 1}", part)); part = []
        if part:
            chapters.append((f"Part {len(chapters) + 1}", part))
        if len(chapters) == 1:
            chapters = [(title or "Read aloud", chapters[0][1])]
    return [(name[:255], paras) for name, paras in chapters if any(x.strip() for x in paras)]


# ---------------------------------------------------------------------------
# The voice
# ---------------------------------------------------------------------------

def _pieces(paragraphs):
    """The chapter's text in pieces of at most CHUNK_CHARS, split between
    paragraphs (or sentences, for a very long one). Joined with "\\n\\n" they
    are exactly the chapter's text."""
    pieces, current = [], ""
    for para in paragraphs:
        parts = [para] if len(para) <= CHUNK_CHARS else re.split(r"(?<=[.!?…”\"])\s+", para)
        # No full stops for a long way (a list, a poem run together): between words.
        split = []
        for part in parts:
            while len(part) > CHUNK_CHARS:
                cut = part.rfind(" ", 0, CHUNK_CHARS)
                cut = cut if cut > 0 else CHUNK_CHARS
                split.append(part[:cut]); part = part[cut:].lstrip()
            split.append(part)
        parts = split
        for k, part in enumerate(parts):
            glue = "\n\n" if k == 0 else " "
            candidate = (current + glue + part) if current else part
            if current and len(candidate) > CHUNK_CHARS:
                pieces.append((current, glue)); current = part
            else:
                current = candidate
    if current:
        pieces.append((current, ""))
    return pieces


def _speak(text, previous="", following="", voice=None, model=None):
    """MP3 bytes and the alignment for `text`, in the site's voice unless
    another ElevenLabs `voice` is given."""
    url = TTS_URL.format(voice=voice or settings.ELEVENLABS_VOICE_ID)
    payload = {"text": text, "model_id": model or _model()}
    if previous:
        payload["previous_text"] = previous[-CONTEXT_CHARS:]
    if following:
        payload["next_text"] = following[:CONTEXT_CHARS]
    body = json.dumps(payload).encode()
    for attempt in range(TRIES):
        request = urllib.request.Request(url, data=body, headers={
            "xi-api-key": settings.ELEVENLABS_API_KEY, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                data = json.loads(answer.read())
            return base64.b64decode(data["audio_base64"]), data.get("alignment") or {}
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", errors="ignore")
            if error.code in (429, 500, 502, 503, 504) and attempt + 1 < TRIES:
                time.sleep(5 * (attempt + 1))
                continue
            raise NarrationUnavailable(f"ElevenLabs answered HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            if attempt + 1 < TRIES:
                time.sleep(5 * (attempt + 1))
                continue
            raise NarrationUnavailable(f"Couldn't reach ElevenLabs: {error}") from error
    raise NarrationUnavailable("ElevenLabs didn't answer.")


def _words(alignment, offset):
    """[[word, start, end], …] from the voice's letter-by-letter timing."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words, current, first, last = [], "", None, None
    for ch, a, b in zip(chars, starts, ends):
        if ch.isspace():
            if current:
                words.append([current, round(first + offset, 3), round(last + offset, 3)])
            current, first, last = "", None, None
            continue
        if not current:
            first = float(a)
        current += ch
        last = float(b)
    if current:
        words.append([current, round(first + offset, 3), round(last + offset, 3)])
    return words


def _duration(path):
    done = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                          capture_output=True, timeout=60)
    try:
        return float(done.stdout.decode().strip())
    except ValueError:
        raise NarrationUnavailable("A piece of audio couldn't be read back.")


def read_chapter(paragraphs, voice=None, model=None):
    """(mp3 bytes, words with times, length in seconds) for one chapter.
    Also used for teachers' lesson notes (apps/lesson_audio), which may
    choose another voice."""
    pieces = _pieces(paragraphs)
    words, offset = [], 0.0
    with tempfile.TemporaryDirectory(prefix="library-voice-") as folder:
        listing = []
        for n, (text, _glue) in enumerate(pieces):
            previous = pieces[n - 1][0] if n else ""
            following = pieces[n + 1][0] if n + 1 < len(pieces) else ""
            audio, alignment = _speak(text, previous, following, voice=voice, model=model)
            path = f"{folder}/piece{n:04d}.mp3"
            with open(path, "wb") as out:
                out.write(audio)
            words.extend(_words(alignment, offset))
            offset += _duration(path)
            listing.append(f"file '{path}'")
        with open(f"{folder}/list.txt", "w") as out:
            out.write("\n".join(listing))
        joined = f"{folder}/chapter.mp3"
        done = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                               "-i", f"{folder}/list.txt", "-c", "copy", joined], capture_output=True, timeout=600)
        if done.returncode:
            raise NarrationUnavailable("The chapter's audio couldn't be joined together.")
        with open(joined, "rb") as src:
            return src.read(), words, offset


# ---------------------------------------------------------------------------
# Keeping a book's read-aloud up to date
# ---------------------------------------------------------------------------

def _hash(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def source_of(item):
    """What the read-aloud is made from: when this changes, it's made again."""
    recordings = "|".join(f"{r.name}={r.audio_file.name}" for r in _recordings(item)) if item.pk else ""
    return _hash(VERSION, item.kind, item.file.name if item.file else "", item.description,
                 item.narration_file.name if item.narration_file else "", recordings,
                 _model(), getattr(settings, "ELEVENLABS_VOICE_ID", ""))


def wants_reading(item):
    has_recordings = bool(item.pk) and item.recordings.exists()
    return (item.kind in READ_KINDS and bool(item.file or item.description or item.narration_file)) or has_recordings


# ---------------------------------------------------------------------------
# The book's own recordings: "Chapter five", "Page 121 to 124" ...
# ---------------------------------------------------------------------------

_UNITS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
_NUMBER_WORDS = "|".join(sorted(list(_UNITS) + list(_TENS) + list(_ORDINALS), key=len, reverse=True))
_NUMBER = rf"(\d+|(?:(?:{_NUMBER_WORDS})(?:[\s-]+(?:{_NUMBER_WORDS}))?)|[ivxlc]+)"
_CHAPTER = re.compile(rf"\b(?:chapter|chap|ch|part|unit|lesson|section|story)\.?\s*{_NUMBER}\b", re.I)
_PAGES = re.compile(r"\b(?:pages?|pgs?|pp?)\.?\s*(\d+)(?:\s*(?:-|–|to|_|and)\s*(\d+))?", re.I)


def number(word):
    """ "5", "five", "twenty-one", "fifth", "V" → 5, 5, 21, 5, 5 (None if not a number)."""
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    parts = re.split(r"[\s-]+", word)
    if all(p in _UNITS or p in _TENS or p in _ORDINALS for p in parts):
        return sum(_UNITS.get(p, 0) + _TENS.get(p, 0) + _ORDINALS.get(p, 0) for p in parts)
    if word and all(ch in _ROMAN for ch in word):
        total = 0
        for i, ch in enumerate(word):
            value = _ROMAN[ch]
            total += -value if i + 1 < len(word) and _ROMAN[word[i + 1]] > value else value
        return total
    return None


def recording_part(name):
    """What a recording's name says it covers: ("chapter", 5), ("pages", 121, 124) or ("other",)."""
    text = re.sub(r"[_]+", " ", name)
    pages = _PAGES.search(text)
    if pages:
        first = int(pages.group(1))
        return ("pages", first, int(pages.group(2) or first))
    chapter = _CHAPTER.search(text)
    if chapter and number(chapter.group(1)) is not None:
        return ("chapter", number(chapter.group(1)))
    return ("other",)


def _natural(name):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _recordings(item):
    """The book's recordings, in reading order: chapters by number, then
    page ranges by page, then anything else by name."""
    def key(recording):
        part = recording_part(recording.name)
        rank = {"chapter": 0, "pages": 1, "other": 2}[part[0]]
        return (rank, part[1] if len(part) > 1 else 0, _natural(recording.name))
    return sorted(item.recordings.all(), key=key)


def recording_title(name):
    """How a recording is shown: "Chapter 5", "Pages 121–124", or its own name."""
    part = recording_part(name)
    if part[0] == "chapter":
        return f"Chapter {part[1]}"
    if part[0] == "pages":
        return f"Page {part[1]}" if part[1] == part[2] else f"Pages {part[1]}–{part[2]}"
    return " ".join(re.sub(r"[_]+", " ", name).split())[:255]


def name_from_file(filename):
    """ "chapter_five.mp3" → "chapter five" """
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return " ".join(re.sub(r"[_]+", " ", stem).split())[:200] or "Recording"


def _chapter_number(heading):
    match = HEADING.match(heading.strip())
    return number(match.group(2)) if match else None


def _page_text(item, first, last, folder):
    """The book's words on pages first to last (PDF books only)."""
    if not item.file or _extension(item.file.name) != "pdf":
        return []
    path = _local_copy(item.file, folder)
    try:
        return [" ".join(p.split()) for p in _pdf_paragraphs(path, first, last) if p.strip()]
    except NarrationUnavailable:
        return []


def _from_recordings(item, chapters, source):
    """One chapter per recording, each with the words it reads (when the
    book's text has them), so the read-along can follow it."""
    from apps.book import read_along

    from .models import LibraryChapter

    by_number = {}
    for name, paras in chapters:
        n = _chapter_number(name)
        if n is not None and n not in by_number:
            by_number[n] = (name, paras)

    kept = {c.order: c for c in LibraryChapter.objects.filter(item=item)}
    recordings = _recordings(item)
    made = 0
    with tempfile.TemporaryDirectory(prefix="library-pages-") as folder:
        for order, recording in enumerate(recordings):
            part = recording_part(recording.name)
            title, paras = recording_title(recording.name), []
            if part[0] == "chapter" and part[1] in by_number:
                heading, paras = by_number[part[1]]
                title = heading
            elif part[0] == "pages":
                paras = _page_text(item, part[1], part[2], folder)
            elif len(recordings) == 1 and chapters:
                # A single recording of the whole book.
                paras = [p for _n, ps in chapters for p in ps]
                title = item.title
            text = "\n\n".join(paras)
            chapter = kept.pop(order, None)
            if chapter is not None and chapter.generated and chapter.audio_file:
                chapter.audio_file.delete(save=False)
            if chapter is None:
                chapter = LibraryChapter(item=item, order=order)
            changed = (chapter.audio_file.name != recording.audio_file.name or chapter.text != text or chapter.generated)
            chapter.title, chapter.text, chapter.generated = title[:255], text, False
            chapter.audio_file.name = recording.audio_file.name
            chapter.audio_url, chapter.source_hash = "", source
            chapter.save()
            if changed and text:
                read_along.measure_in_background(chapter)
            made += 1
    for extra in kept.values():
        if extra.generated and extra.audio_file:
            extra.audio_file.delete(save=False)
        extra.delete()
    return made


STALE = 15 * 60            # a claim not refreshed for this long belonged to a run that died


def _claim(item, token):
    """Take the book, unless another run is working on it right now."""
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from .models import LibraryItem

    now = timezone.now()
    free = Q(narration_owner="") | Q(narration_updated__isnull=True) | Q(narration_updated__lt=now - timedelta(seconds=STALE))
    return LibraryItem.objects.filter(pk=item.pk).filter(free).update(narration_owner=token, narration_updated=now) == 1


def _set(item, **values):
    from django.utils import timezone

    from .models import LibraryItem

    values.setdefault("narration_updated", timezone.now())      # still alive
    LibraryItem.objects.filter(pk=item.pk).update(**values)
    for key, value in values.items():
        setattr(item, key, value)


def _save_timing(chapter, words, duration):
    """The words' timings as the voice read them: ready, and exact."""
    from django.contrib.contenttypes.models import ContentType

    from apps.book import read_along
    from apps.book.models import ReadAlongTiming

    ReadAlongTiming.objects.update_or_create(
        content_type=ContentType.objects.get_for_model(chapter), object_id=chapter.pk,
        defaults={"fingerprint": read_along._fingerprint(chapter), "status": ReadAlongTiming.STATUS_READY,
                  "engine": "voice", "words": words, "speech": [], "duration": duration,
                  "quality": 1.0, "error": ""},
    )


def narrate(item, force=False):
    """Make (or refresh) the item's read-aloud now. Chapters already made
    from the same words are kept, so this can be run again after a stop."""
    import uuid

    token = uuid.uuid4().hex
    if not _claim(item, token):
        logger.info("Library read-aloud for %s is already being made elsewhere.", item.pk)
        return
    try:
        _narrate(item, force)
    finally:
        _set(item, narration_owner="")


def _narrate(item, force):
    from apps.book import read_along

    from .models import LibraryChapter

    if not wants_reading(item):
        LibraryChapter.objects.filter(item=item).delete()
        _set(item, narration_status="", narration_note="", narration_chars=0, narration_source="")
        return
    source = source_of(item)
    try:
        _set(item, narration_status="working", narration_note="Reading the book…")
        paragraphs = book_paragraphs(item)
        chapters = main_chapters(paragraphs, item.title)

        if item.recordings.exists():
            # Its own recordings: a chapter each, matched to the book's words.
            made = _from_recordings(item, chapters, source)
            chars = sum(len("\n\n".join(paras)) for _name, paras in chapters)
            _set(item, narration_status="ready",
                 narration_note=f"Using {made} uploaded recording{'s' if made != 1 else ''}.",
                 narration_chars=chars, narration_source=source)
            return

        if not chapters:
            _set(item, narration_status="off", narration_note="No text to read aloud was found in this item.",
                 narration_chars=0, narration_source=source)
            LibraryChapter.objects.filter(item=item).delete()
            return
        chars = sum(len("\n\n".join(paras)) for _name, paras in chapters)

        if item.narration_file:
            # Its own recording: one chapter of the whole main text, measured.
            LibraryChapter.objects.filter(item=item).delete()
            chapter = LibraryChapter.objects.create(
                item=item, order=0, title=item.title, text="\n\n".join(p for _n, paras in chapters for p in paras),
                audio_file=item.narration_file.name, generated=False, source_hash=source)
            read_along.measure_in_background(chapter)
            _set(item, narration_status="ready", narration_note="Using the uploaded recording.",
                 narration_chars=chars, narration_source=source)
            return

        if not voice_configured():
            raise NarrationUnavailable("The voice isn't set up (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID and ffmpeg are needed).")
        if chars > _max_chars():
            raise NarrationUnavailable(
                f"The book has {chars:,} characters to read, over the limit of {_max_chars():,} "
                "(LIBRARY_NARRATION_MAX_CHARS). Raise the limit or upload a recording.")

        kept = {c.order: c for c in LibraryChapter.objects.filter(item=item)}
        for order, (name, paras) in enumerate(chapters):
            text = "\n\n".join(paras)
            wanted = _hash(VERSION, text, _model(), getattr(settings, "ELEVENLABS_VOICE_ID", ""))
            chapter = kept.pop(order, None)
            if chapter and not force and chapter.generated and chapter.source_hash == wanted and chapter.audio_file:
                continue                                     # already made from these words
            _set(item, narration_note=f"chapter {order + 1} of {len(chapters)}")
            audio, words, duration = read_chapter(paras)
            if chapter is None:
                chapter = LibraryChapter(item=item, order=order)
            elif chapter.audio_file and chapter.generated:
                chapter.audio_file.delete(save=False)
            chapter.title, chapter.text, chapter.generated, chapter.source_hash = name, text, True, wanted
            chapter.audio_file.save(f"{item.slug[:60]}-{order + 1:02d}.mp3", ContentFile(audio), save=False)
            chapter.save()
            _save_timing(chapter, words, duration)
        for extra in kept.values():                         # chapters the book no longer has
            if extra.generated and extra.audio_file:
                extra.audio_file.delete(save=False)
            extra.delete()
        _set(item, narration_status="ready", narration_note=f"{len(chapters)} chapter{'s' if len(chapters) != 1 else ''}",
             narration_chars=chars, narration_source=source)
    except NarrationUnavailable as error:
        logger.warning("Library read-aloud for %s failed: %s", item.pk, error)
        _set(item, narration_status="failed", narration_note=str(error)[:255], narration_source=source)
    except Exception as error:                               # never leave it "working" for ever
        logger.exception("Library read-aloud for %s failed", item.pk)
        _set(item, narration_status="failed", narration_note=f"Something went wrong: {error}"[:255], narration_source=source)


def queue(item, force=False):
    """Make the read-aloud in the background, once at a time per item. It
    starts once the save that asked for it is committed (so it sees the new
    recordings), and if asked again while running, it runs once more."""
    from django.db import transaction

    with _lock:
        if item.pk in _queued:
            _again.add(item.pk)
            return
        _queued.add(item.pk)

    def run():
        from .models import LibraryItem

        close_old_connections()
        try:
            fresh = LibraryItem.objects.filter(pk=item.pk).first()
            if fresh:
                narrate(fresh, force=force)
        finally:
            with _lock:
                _queued.discard(item.pk)
                again = item.pk in _again
                _again.discard(item.pk)
            close_old_connections()
            if again:
                queue(item, force=force)

    transaction.on_commit(lambda: _pool.submit(run))


def needs_narration(item):
    """Due to be made: new, changed, asked for again, or left unfinished."""
    if not wants_reading(item):
        return bool(item.narration_status)
    if item.narration_redo:
        return True
    return item.narration_source != source_of(item) or item.narration_status == "working"


def refresh(item):
    """After the recordings change (added or removed in the control room):
    rebuild the read-aloud's chapters from them."""
    when_saved(type(item), item)


def when_saved(sender, instance, created=False, raw=False, **kwargs):
    """A book or story saved: make its read-aloud if it's new or changed."""
    if raw or getattr(settings, "TESTING", False):
        return
    try:
        redo = instance.narration_redo
        if redo:
            _set(instance, narration_redo=False)
        if not (redo or needs_narration(instance)):
            return
        if not wants_reading(instance):
            queue(instance)                                  # tidy away old chapters
            return
        if not (redo or instance.narration_file or instance.recordings.exists() or auto_for(instance)):
            _set(instance, narration_status="off",
                 narration_note="Not made automatically: tick “Make the read-aloud again” to make it.",
                 narration_source=source_of(instance))
            return
        _set(instance, narration_status="working", narration_note="Waiting to start…")
        queue(instance, force=redo)
    except Exception:
        logger.exception("Couldn't start the read-aloud for library item %s", instance.pk)
