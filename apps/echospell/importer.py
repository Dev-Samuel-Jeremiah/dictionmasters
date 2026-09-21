"""
Bringing a whole level of the Echospell book into the site at once.

The book repeats the same shape for every group, and that shape is what
this reads:

    LEVEL 7 GROUP 1        ← the heading that starts a group
    1. Today  2. Breakfast … ← the words, numbered, in one or more columns
    Art in its Form          ← the passage: its title, then its paragraphs
    Conversation Group 1     ← the dialogue: numbered lines, "SPEAKER: …"
    Vocabulary Group 1       ← left alone, as asked

Anything before the first group heading (the book's own introduction) is
passed over, as are page numbers and the vocabulary pages.

Nothing is written while reading. `parse` gives back what it found, the
control room shows it, and only then does `apply_import` save it — so an
admin sees exactly what is about to happen before anything changes.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.db import transaction

from .models import CardLesson, Category, Dialogue, DialogueLine, Group, Level, Passage

# The card types a group's pages become. Vocabulary is deliberately absent.
SPELLING = "spelling"
PASSAGE = "passage-reading"
DIALOGUE = "dialogue"

MAX_BYTES = 25 * 1024 * 1024
READ_TIMEOUT = 120

# "LEVEL 7 GROUP 1", "Level 7 Group 1", "PRE-LEVEL GROUP 3"
_HEADING = re.compile(r"^[^\S\n]*(?:LEVEL\s+(\d{1,2})|(PRE[\s-]*LEVEL))\s+GROUP\s+(\d{1,2})[^\S\n]*$",
                      re.IGNORECASE | re.MULTILINE)
# "Conversation Group 1" / "Dialogue Group 1"
_DIALOGUE_HEAD = re.compile(r"^\s*(?:conversation|dialogue)\s+group\s*\d*\s*$", re.IGNORECASE | re.MULTILINE)
_VOCAB_HEAD = re.compile(r"^\s*vocabulary\s+group\s*\d*\s*$", re.IGNORECASE | re.MULTILINE)
# "1. Today" or "10.Category" or "3) Liaison", several to a line in columns
_WORD = re.compile(r"(\d{1,2})\s*[.)]\s*([^\W\d_][\w'’\-]*(?:[ ][^\W\d_][\w'’\-]*){0,3})", re.UNICODE)
# "1.   JASMINE: Curtis, your organelle …"
_SPEAKER = re.compile(r"^\s*(?:(\d{1,2})\s*[.)]\s*)?([^\W\d_][\w'’.\- ]{0,24}?)\s*:\s(?=\S)", re.UNICODE | re.MULTILINE)
_PAGE_NUMBER = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,7})\s*$", re.IGNORECASE)
# A column of words printed at the edge of the page wraps, leaving its
# number stranded at the end of one line and its word alone on the next
# ("17." then "Genre"). They belong together.
_DANGLING_NUMBER = re.compile(r"(\d{1,2}\s*[.)])[^\S\n]*\n[^\S\n]*(?=[^\W\d_])")


class CannotRead(Exception):
    """The file couldn't be read as text."""


# ---------------------------------------------------------------------------
# Getting the words out of the file
# ---------------------------------------------------------------------------

def read_text(upload):
    """The text of an uploaded book — PDF, Word file or plain text."""
    name = (getattr(upload, "name", "") or "").lower()
    if getattr(upload, "size", 0) > MAX_BYTES:
        raise CannotRead("That file is too big — up to 25MB, please.")
    data = upload.read()
    upload.seek(0)
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return _from_pdf(data)
    if name.endswith((".docx", ".doc")) or data[:2] == b"PK":
        return _from_word(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError as error:
            raise CannotRead("That file isn't a PDF, a Word file or plain text.") from error


def _from_pdf(data):
    if not shutil.which("pdftotext"):
        raise CannotRead(
            "This server can't read PDFs (pdftotext isn't installed). "
            "Save the level as a Word file (.docx) and upload that instead."
        )
    with tempfile.TemporaryDirectory(prefix="echospell-import-") as folder:
        source = Path(folder) / "book.pdf"
        source.write_bytes(data)
        out = Path(folder) / "book.txt"
        try:
            # -layout keeps the word columns side by side, which is how the
            # book prints them.
            subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(source), str(out)],
                           capture_output=True, timeout=READ_TIMEOUT, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            raise CannotRead("That PDF couldn't be read. Try saving it as a Word file instead.") from error
        return out.read_text(encoding="utf-8", errors="ignore")


def _from_word(data):
    try:
        import docx
    except ImportError as error:                      # pragma: no cover
        raise CannotRead("This server can't read Word files.") from error
    with tempfile.TemporaryDirectory(prefix="echospell-import-") as folder:
        source = Path(folder) / "book.docx"
        source.write_bytes(data)
        try:
            document = docx.Document(str(source))
        except Exception as error:
            raise CannotRead("That Word file couldn't be read.") from error
        return "\n".join(paragraph.text for paragraph in document.paragraphs)


# ---------------------------------------------------------------------------
# Reading the shape of the book
# ---------------------------------------------------------------------------

def _tidy(text):
    """The text with the printer's furniture taken out: page numbers, the
    form feeds between pages, and trailing spaces."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    kept = [line.rstrip() for line in text.split("\n")]
    text = "\n".join("" if _PAGE_NUMBER.match(line) else line for line in kept)
    return _DANGLING_NUMBER.sub(r"\1 ", text)


def _paragraphs(lines):
    """Lines as paragraphs: a blank line ends one, and the lines within a
    paragraph are joined back into running text."""
    out, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            out.append(" ".join(current))
            current = []
    if current:
        out.append(" ".join(current))
    return out


def _words_in(region):
    """The numbered words, in the book's own order. Handles one word per
    line and the book's columns, where a line holds five of them."""
    found = {}
    for number, word in _WORD.findall(region):
        number = int(number)
        word = " ".join(word.split()).strip(" -")
        if word and number not in found:
            found[number] = word
    return [found[number] for number in sorted(found)]


def _split_group(block):
    """One group's text, cut into its words, its passage and its dialogue.
    Vocabulary is dropped."""
    vocab = _VOCAB_HEAD.search(block)
    if vocab:
        block = block[:vocab.start()]
    dialogue_head = _DIALOGUE_HEAD.search(block)
    before, dialogue_region = (block[:dialogue_head.start()], block[dialogue_head.end():]) if dialogue_head \
        else (block, "")

    # The words run until the first line with no numbered word on it —
    # which is the passage's title.
    lines = before.split("\n")
    words_end = len(lines)
    started = False
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _WORD.search(line):
            started = True
            continue
        if started:
            words_end = index
            break
    return "\n".join(lines[:words_end]), "\n".join(lines[words_end:]), dialogue_region


def _read_passage(region):
    """{"title": …, "body": …} — the first line is the title, the rest the
    passage itself."""
    paragraphs = _paragraphs(region.split("\n"))
    if not paragraphs:
        return None
    title, body = paragraphs[0], paragraphs[1:]
    # A one-paragraph region is a passage with no title of its own.
    if not body:
        return {"title": "", "body": title}
    return {"title": " ".join(title.split())[:150], "body": "\n\n".join(body)}


def _read_dialogue(region):
    """[{"speaker": "EVA", "text": "…"}, …] from the numbered lines."""
    region = region.strip("\n")
    if not region.strip():
        return []
    marks = list(_SPEAKER.finditer(region))
    lines = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(region)
        said = " ".join(region[mark.end():end].split())
        speaker = " ".join(mark.group(2).split()).strip(" .")
        if said and speaker:
            lines.append({"speaker": speaker[:20], "text": said})
    return lines


def parse(text):
    """What the book holds:

    {"level": "Level 7", "groups": [{"number": 1, "words": [...],
      "passage": {"title", "body"}, "dialogue": [{"speaker", "text"}],
      "notes": [...]}]}

    `notes` are things an admin should look at — a group with no passage,
    or fewer words than the book usually carries."""
    text = _tidy(text)
    headings = list(_HEADING.finditer(text))
    if not headings:
        raise CannotRead(
            "No group headings were found. The book should have lines like "
            "“LEVEL 7 GROUP 1” above each group's words."
        )

    levels = {f"Level {match.group(1)}" if match.group(1) else "Pre-Level" for match in headings}
    groups = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end():end]
        words_region, passage_region, dialogue_region = _split_group(block)

        words = _words_in(words_region)
        passage = _read_passage(passage_region)
        dialogue = _read_dialogue(dialogue_region)

        notes = []
        if not words:
            notes.append("No words were found for this group.")
        elif len(words) < 10:
            notes.append(f"Only {len(words)} word{'s' if len(words) != 1 else ''} were found — check the list.")
        if not passage:
            notes.append("No passage was found.")
        if not dialogue:
            notes.append("No conversation was found.")
        groups.append({
            "number": int(heading.group(3)),
            "words": words,
            "passage": passage,
            "dialogue": dialogue,
            "notes": notes,
        })

    return {
        "level": sorted(levels)[0] if len(levels) == 1 else "",
        "levels_seen": sorted(levels),
        "groups": groups,
    }


# ---------------------------------------------------------------------------
# Writing it in
# ---------------------------------------------------------------------------

FILL_GAPS = "fill"
REPLACE = "replace"


def _card_types(level):
    """The card types this level needs, linked to it if they aren't yet."""
    types, missing, _seen = _card_types_seen(level)
    linked = []
    for slug, found in types.items():
        if found and not level.categories.filter(pk=found.pk).exists():
            level.categories.add(found)
            linked.append(found.name)
    return types, missing, linked


def describe_plan(parsed, level, mode=FILL_GAPS):
    """What saving would do, without doing any of it — one line per group,
    so an admin can see it before agreeing to it."""
    types, missing, _linked = _card_types_seen(level)
    plan = []
    for found in parsed["groups"]:
        group = Group.objects.filter(level=level, number=found["number"]).first() if level else None
        doing = []

        if found["words"]:
            card = (CardLesson.objects.filter(group=group, category=types[SPELLING]).first()
                    if group and types[SPELLING] else None)
            doing.append(_what(card and card.word.strip(), f"{len(found['words'])} spelling words", mode))
        if found["passage"]:
            passage = getattr(group, "passage", None) if group else None
            doing.append(_what(passage and passage.body.strip(), "the passage", mode))
        if found["dialogue"]:
            dialogue = getattr(group, "dialogue", None) if group else None
            has = dialogue.lines.exists() if dialogue else False
            doing.append(_what(has, f"the conversation ({len(found['dialogue'])} lines)", mode))

        plan.append({**found, "exists": bool(group), "doing": doing})
    return {"plan": plan, "missing_types": missing}


def _what(already_there, what, mode):
    if not already_there:
        return f"{what} — will be added"
    if mode == REPLACE:
        return f"{what} — will be rewritten (recordings kept)"
    return f"{what} — already there, left alone"


def _card_types_seen(level):
    """The card types, without linking anything to the level yet."""
    types = {slug: Category.objects.filter(slug=slug).first() for slug in (SPELLING, PASSAGE, DIALOGUE)}
    missing = [slug for slug, found in types.items() if found is None]
    return types, missing, []


@transaction.atomic
def apply_import(parsed, level, mode=FILL_GAPS):
    """Save what `parse` found. Recordings are never touched: a card keeps
    its Full and Quick audio even when its words are rewritten.

    mode FILL_GAPS writes only what is empty; REPLACE also rewrites text
    that is already there."""
    types, missing, linked = _card_types(level)
    report = {"level": level.name, "linked": linked, "missing_types": missing,
              "groups": [], "created": 0, "updated": 0, "left": 0}

    for found in parsed["groups"]:
        group, made = Group.objects.get_or_create(level=level, number=found["number"])
        done = {"number": found["number"], "group_created": made, "did": [], "left": []}

        if found["words"] and types[SPELLING]:
            card = CardLesson.objects.filter(group=group, category=types[SPELLING]).order_by("order", "pk").first()
            words = "\n".join(found["words"])
            if card is None:
                CardLesson.objects.create(group=group, category=types[SPELLING], word=words)
                done["did"].append(f"{len(found['words'])} spelling words added")
            elif mode == REPLACE and card.word.strip() != words:
                card.word = words
                card.save(update_fields=["word"])       # its recordings stay as they are
                done["did"].append(f"{len(found['words'])} spelling words rewritten")
            else:
                done["left"].append("spelling words already there")

        if found["passage"] and types[PASSAGE]:
            passage = getattr(group, "passage", None)
            body = found["passage"]["body"]
            title = found["passage"]["title"]
            if passage is None:
                Passage.objects.create(group=group, title=title, body=body)
                done["did"].append("passage added")
            elif mode == REPLACE and (passage.body.strip() != body.strip() or passage.title != title):
                passage.title, passage.body = title, body
                passage.save(update_fields=["title", "body"])
                done["did"].append("passage rewritten")
            else:
                done["left"].append("passage already there")

        if found["dialogue"] and types[DIALOGUE]:
            dialogue = getattr(group, "dialogue", None)
            if dialogue is None:
                dialogue = Dialogue.objects.create(group=group)
                _write_lines(dialogue, found["dialogue"])
                done["did"].append(f"conversation added ({len(found['dialogue'])} lines)")
            elif mode == REPLACE:
                _write_lines(dialogue, found["dialogue"])
                done["did"].append(f"conversation rewritten ({len(found['dialogue'])} lines)")
            else:
                done["left"].append("conversation already there")

        report["created"] += sum(1 for line in done["did"] if "added" in line)
        report["updated"] += sum(1 for line in done["did"] if "rewritten" in line)
        report["left"] += len(done["left"])
        report["groups"].append(done)
    return report


def _write_lines(dialogue, lines):
    dialogue.lines.all().delete()
    DialogueLine.objects.bulk_create([
        DialogueLine(dialogue=dialogue, speaker=line["speaker"], text=line["text"], order=number)
        for number, line in enumerate(lines)
    ])


def level_for(name, create=False):
    """The Level this book belongs to, made if asked for."""
    level = Level.objects.filter(name__iexact=name).first()
    if level is None and create and name:
        level = Level.objects.create(name=name)
    return level
