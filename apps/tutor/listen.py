"""
Hearing the reader, and judging each word against the passage.

A clip of the learner reading one sentence (or saying one word again) is
turned into a small MP3 and transcribed by Whisper on Groq — never told
what the text says, and prompted to write words as they sound, so it
writes down what was actually said rather than what should have been. That transcript is lined up with the
sentence, word by word, and each word on the page comes back as:

    ok       said, or said so it sounds the same ("their" / "there")
    wrong    something else was said in its place — with which sound
             changed, when the dictionary knows both words
    missed   not said at all

Lining up allows for the way people really read: a word repeated, a
false start put right ("the bag… the back"), a filler "um" — extra words
cost little, so they're passed over rather than blamed on the text.

Honest limit: a transcriber hears words, not sounds, and inside a
sentence it still sometimes hears the word it expects ("sink it will
rain" can come back as "think"). Clear misreadings ("tree" for "three",
"berry" for "very") are caught and named; the rest aren't blamed on the
learner, so a correct reading is never marked wrong.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from difflib import SequenceMatcher

from apps.book.read_along import AlignmentUnavailable, _groq, _key

from . import pronounce

MAX_CLIP_SECONDS = 45
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
CONVERT_TIMEOUT = 30

# Extra words heard (repeats, self-corrections, "um") cost less than a
# word on the page being wrong, so the line-up passes over them.
COST_EXTRA = 0.6
COST_WRONG = 1.0
COST_MISSED = 1.0

# Small words a reader can drop without the meaning changing much. They
# still count against accuracy, but the tutor doesn't stop the reading
# to model "a" or "the".
LIGHT_WORDS = {
    "a", "an", "the", "and", "of", "to", "in", "on", "at", "is", "it", "as", "or", "but",
    "for", "by", "so", "be", "do", "if", "up", "we", "he", "me", "my", "i", "you",
}

# Between sentences: after . ! ? or … (and any closing quote or bracket,
# which stays with its sentence), before a capital or a number.
_SPLIT = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"'”’)\]]))\s+(?=[\"'“‘(\[]*[A-Z0-9])")
LONG_SENTENCE = 24


# Whisper tidies speech into the words it expects — "tree" for "three"
# comes back as "three", which would hide the very mistakes the tutor is
# for. Shown a transcript written as it sounds, it keeps to what it hears.
# (Tested: this still writes a correct reading correctly.)
LITERAL = (
    "Transcribe exactly what is said, sound by sound, even when words are mispronounced: "
    "I tink dat de tree boys sink so. Dis is berry good, wiv my broder."
)


class NotHeard(Exception):
    """Nothing usable was heard — silence, or the clip couldn't be read."""


# ---------------------------------------------------------------------------
# The passage, sentence by sentence
# ---------------------------------------------------------------------------

def sentences(text):
    """The passage as the tutor reads it with the learner:
    [{"text": "...", "words": [{"text": "Timi", "key": "timi"}, ...]}, ...].

    Split at full stops, question and exclamation marks and paragraph
    breaks. A very long sentence is split once more at the comma nearest
    its middle, so no one has to hold thirty words in a single breath."""
    pieces = []
    paragraphs = [" ".join(p.split()) for p in re.split(r"\r?\n", str(text or ""))]
    for number, paragraph in enumerate(p for p in paragraphs if p):
        pieces += [(number, part.strip()) for part in _SPLIT.split(paragraph) if part.strip()]

    out = []
    for number, piece in pieces:
        tokens = piece.split()
        if len(tokens) > LONG_SENTENCE:
            commas = [i for i, token in enumerate(tokens[:-3]) if token.endswith((",", ";", ":")) and i >= 4]
            if commas:
                cut = min(commas, key=lambda i: abs(i - len(tokens) / 2)) + 1
                out += [(number, tokens[:cut]), (number, tokens[cut:])]
                continue
        out.append((number, tokens))
    return [
        {"text": " ".join(tokens), "paragraph": number,
         "words": [{"text": token, "key": _key(token)} for token in tokens]}
        for number, tokens in out if any(_key(token) for token in tokens)
    ]


# ---------------------------------------------------------------------------
# Hearing the clip
# ---------------------------------------------------------------------------

# Groq reads these as they come from the browser, so nothing is converted
# and nothing waits on ffmpeg.
READY_MADE = {"webm": "webm", "ogg": "ogg", "opus": "ogg", "mp4": "mp4", "m4a": "m4a",
              "mp3": "mp3", "wav": "wav", "flac": "flac", "mpeg": "mp3", "mpga": "mp3"}


def _suffix(name, content_type):
    for source in (str(name or "").lower().rsplit(".", 1)[-1], str(content_type or "").lower()):
        for key, kind in READY_MADE.items():
            if key in source:
                return kind
    return ""


def clip_folder(session_id, clip=None):
    """Where a recording being uploaded while it is still being spoken is
    kept. One folder per reading, cleared when the reading ends."""
    folder = os.path.join(tempfile.gettempdir(), "dictionmasters-tutor", str(int(session_id)))
    if clip:
        folder = os.path.join(folder, re.sub(r"[^a-z0-9]", "", str(clip).lower())[:32] or uuid.uuid4().hex)
    return folder


def keep_piece(session_id, clip, number, upload, kind):
    """Keep one piece of a recording as it arrives."""
    folder = clip_folder(session_id, clip)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{int(number):04d}.part")
    with open(path, "wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    with open(os.path.join(folder, "kind"), "w") as handle:
        handle.write(kind or "webm")
    return sum(os.path.getsize(os.path.join(folder, name)) for name in os.listdir(folder))


def gather(session_id, clip):
    """The pieces of a recording, joined back into one file. The pieces a
    MediaRecorder gives are made to be joined exactly like this."""
    folder = clip_folder(session_id, clip)
    if not os.path.isdir(folder):
        raise NotHeard("That recording didn't arrive.")
    parts = sorted(name for name in os.listdir(folder) if name.endswith(".part"))
    if not parts:
        raise NotHeard("That recording didn't arrive.")
    kind = "webm"
    try:
        with open(os.path.join(folder, "kind")) as handle:
            kind = handle.read().strip() or "webm"
    except OSError:
        pass
    joined = os.path.join(folder, f"clip.{kind}")
    with open(joined, "wb") as out:
        for name in parts:
            with open(os.path.join(folder, name), "rb") as piece:
                shutil.copyfileobj(piece, out)
    return joined


def forget(session_id, clip=None):
    shutil.rmtree(clip_folder(session_id, clip), ignore_errors=True)


def sweep(older_than=2 * 60 * 60):
    """Clear away pieces left behind by a reading that was never finished —
    a closed tab, a phone that went to sleep."""
    root = os.path.join(tempfile.gettempdir(), "dictionmasters-tutor")
    try:
        names = os.listdir(root)
    except OSError:
        return
    stale = time.time() - older_than
    for name in names:
        folder = os.path.join(root, name)
        try:
            if os.path.getmtime(folder) < stale:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def transcribe_file(path, kind=""):
    """[(word, start, end), …] heard in a recording already on disk."""
    if os.path.getsize(path) > MAX_UPLOAD_BYTES:
        raise NotHeard("The recording is too long.")
    try:
        return _hear(path)
    except AlignmentUnavailable as error:
        # A file it couldn't read is worth one go through ffmpeg.
        if "HTTP 400" not in str(error):
            raise
        return _hear(_converted(path))


def _hear(path):
    try:
        # Never the passage as a hint: the tutor needs what was said, not
        # what should have been.
        words = _groq(path, hint=LITERAL)
    except AlignmentUnavailable as error:
        if "no words" in str(error):
            raise NotHeard("Nothing was heard.") from error
        raise
    return [(text, float(start), float(end)) for text, start, end in words]


def _converted(path):
    if not shutil.which("ffmpeg"):
        raise AlignmentUnavailable("ffmpeg is not installed.")
    out = f"{path}.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path, "-t", str(MAX_CLIP_SECONDS),
             "-ac", "1", "-ar", "16000", "-b:a", "48k", out],
            capture_output=True, timeout=CONVERT_TIMEOUT, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise NotHeard("The recording couldn't be read.") from error
    return out


def transcribe(upload):
    """[(word, start, end), …] heard in an uploaded clip (a Django
    UploadedFile). Raises NotHeard for silence or an unreadable clip, and
    AlignmentUnavailable when the transcriber can't be reached."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise NotHeard("The recording is too long.")
    kind = _suffix(upload.name, upload.content_type) or "webm"
    with tempfile.TemporaryDirectory(prefix="tutor-") as folder:
        path = os.path.join(folder, f"clip.{kind}")
        with open(path, "wb") as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        return transcribe_file(path, kind)


# ---------------------------------------------------------------------------
# Judging it
# ---------------------------------------------------------------------------

def _close_spelling(a, b):
    return SequenceMatcher(None, a, b).ratio() >= 0.7


def same_word(expected, heard, name=False):
    """Would a listener accept `heard` as the word on the page? Judged by
    how the two sound in British English, so "there" for "their" — the
    transcriber's spelling, not the reader's mistake — is no mistake, and
    neither is "farther" for "father", which in British English is the
    very same sound."""
    a, b = _key(expected), _key(heard)
    if not a or not b:
        return False
    if a == b or pronounce.sound_alike(expected, heard):
        return True
    # A name the transcriber had to guess the spelling of ("Timi" written
    # as "Timmy", "Emeka" as "Ameka"): near enough in sound and spelling.
    if name and a[0] == b[0]:
        return _close_spelling(a, b) or _close_spelling(
            "".join(pronounce.sounds(expected)), "".join(pronounce.sounds(heard)))
    return False


def line_up(expected, heard):
    """Pair each page word with what was heard for it.

    `expected` is a sentence's words ([{"text", "key"}]), `heard` the
    transcript ([(word, start, end)]). Returns one entry per page word:
    {"status": "ok"|"wrong"|"missed"|"skip", "heard": str, "at": index}.
    "skip" is a token with nothing to say (a dash)."""
    page = [(i, word) for i, word in enumerate(expected) if word["key"]]
    names = {i for i, word in page if i and word["text"][:1].isupper()}
    said_at = [index for index, word in enumerate(heard) if _key(word[0])]
    said = [heard[index] for index in said_at]
    n, m = len(page), len(said)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    step = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            here = cost[i][j]
            if here == INF:
                continue
            if i < n and j < m:
                word = page[i][1]["text"]
                if same_word(word, said[j][0], name=page[i][0] in names):
                    moves = [(i + 1, j + 1, 0.0, "ok")]
                elif j + 1 < m and _key(word) == _key(said[j][0]) + _key(said[j + 1][0]):
                    moves = [(i + 1, j + 2, 0.0, "ok")]   # "well-known" heard as "well known"
                else:
                    moves = [(i + 1, j + 1, COST_WRONG, "wrong")]
            else:
                moves = []
            if i < n:
                moves.append((i + 1, j, COST_MISSED, "missed"))
            if j < m:
                moves.append((i, j + 1, COST_EXTRA, "extra"))
            for ni, nj, extra, kind in moves:
                if here + extra < cost[ni][nj]:
                    cost[ni][nj] = here + extra
                    step[ni][nj] = (i, j, kind)

    verdicts = {}
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, kind = step[i][j]
        if kind in ("ok", "wrong"):
            verdicts[page[pi][0]] = {"status": kind, "heard": said[pj][0].strip(".,!?;:\"'"), "at": said_at[pj]}
        elif kind == "missed":
            verdicts[page[pi][0]] = {"status": "missed", "heard": "", "at": None}
        i, j = pi, pj

    result = []
    for index, word in enumerate(expected):
        result.append(verdicts.get(index) or {"status": "skip", "heard": "", "at": None})
    return result


def judge_sentence(expected, heard):
    """The verdict on one reading of a sentence, ready for the page."""
    lined = line_up(expected, heard)
    words = []
    for index, (word, verdict) in enumerate(zip(expected, lined)):
        entry = {"i": index, "status": verdict["status"]}
        if verdict["status"] == "wrong":
            entry["heard"] = verdict["heard"]
            changes = pronounce.sound_changes(word["text"], verdict["heard"])
            entry["tips"] = _tips(changes)
            entry["patterns"] = [list(pair) for pair in pronounce.patterns(changes)]
        words.append(entry)

    judged = [w for w in words if w["status"] != "skip"]
    right = sum(1 for w in judged if w["status"] == "ok")
    # Worth stopping for: every word read wrongly, and any word of weight
    # that was left out. A dropped "the" is noted but not made a fuss of.
    to_model = [
        w["i"] for w in words
        if w["status"] == "wrong"
        or (w["status"] == "missed" and expected[w["i"]]["key"] not in LIGHT_WORDS)
    ]
    matched = [heard[v["at"]] for v in lined if v["status"] in ("ok", "wrong") and v["at"] is not None]
    seconds = (max(end for _w, _s, end in matched) - min(start for _w, start, _e in matched)) if matched else 0.0
    return {
        "words": words,
        "right": right,
        "total": len(judged),
        "seconds": round(max(seconds, 0.0), 2),
        "model": to_model,
        # Most of it lost: hear the whole sentence and read it again.
        "again": bool(judged) and right / len(judged) < 0.5,
        "heard": " ".join(word for word, _s, _e in heard)[:400],
    }


def judge_word(expected_text, heard):
    """Did the learner say the one word they were asked to?"""
    for word, _start, _end in heard:
        if same_word(expected_text, word, name=True):
            return {"ok": True, "heard": word}
    guess = heard[0][0].strip(".,!?;:\"'") if heard else ""
    changes = pronounce.sound_changes(expected_text, guess) if guess else []
    return {"ok": False, "heard": guess, "tips": _tips(changes)}


def _tips(changes):
    """At most two things to listen for. A swapped sound says the most;
    a sound left out or added only matters when nothing was swapped."""
    swaps = [change for change in changes if change["kind"] == "swap"]
    return [pronounce.explain(change) for change in (swaps or changes)][:2]
