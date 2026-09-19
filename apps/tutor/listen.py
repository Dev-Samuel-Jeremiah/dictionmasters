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

def transcribe(upload):
    """[(word, start, end), …] heard in an uploaded clip (a Django
    UploadedFile). Raises NotHeard for silence or an unreadable clip, and
    AlignmentUnavailable when the transcriber can't be reached."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise NotHeard("The recording is too long.")
    if not shutil.which("ffmpeg"):
        raise AlignmentUnavailable("ffmpeg is not installed.")
    with tempfile.TemporaryDirectory(prefix="tutor-") as folder:
        raw = os.path.join(folder, "clip.bin")
        with open(raw, "wb") as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        clip = os.path.join(folder, "clip.mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", raw, "-t", str(MAX_CLIP_SECONDS),
                 "-ac", "1", "-ar", "16000", "-b:a", "48k", clip],
                capture_output=True, timeout=CONVERT_TIMEOUT, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            raise NotHeard("The recording couldn't be read.") from error
        try:
            # Never the passage as a hint: the tutor needs what was said,
            # not what should have been.
            words = _groq(clip, hint=LITERAL)
        except AlignmentUnavailable as error:
            if "no words" in str(error):
                raise NotHeard("Nothing was heard.") from error
            raise
    return [(text, float(start), float(end)) for text, start, end in words]


# ---------------------------------------------------------------------------
# Judging it
# ---------------------------------------------------------------------------

def _soundex(word):
    groups = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"),
              "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return ""
    code, last = word[0], groups.get(word[0], "")
    for letter in word[1:]:
        digit = groups.get(letter, "")
        if digit and digit != last:
            code += digit
        if letter not in "hw":
            last = digit
    return (code + "000")[:4]


def _close_spelling(a, b):
    return SequenceMatcher(None, a, b).ratio() >= 0.65 or _soundex(a) == _soundex(b)


def same_word(expected, heard):
    """Would a listener accept `heard` as the word on the page?"""
    a, b = _key(expected), _key(heard)
    if not a or not b:
        return False
    if a == b:
        return True
    if pronounce.sound_alike(expected, heard):
        return True
    # A name or local word the dictionary doesn't know ("Timi", "Emeka"):
    # the transcriber has to guess the spelling, so a close one will do.
    if not pronounce.known(expected):
        return a[0] == b[0] and _close_spelling(a, b)
    return False


def line_up(expected, heard):
    """Pair each page word with what was heard for it.

    `expected` is a sentence's words ([{"text", "key"}]), `heard` the
    transcript ([(word, start, end)]). Returns one entry per page word:
    {"status": "ok"|"wrong"|"missed"|"skip", "heard": str, "at": index}.
    "skip" is a token with nothing to say (a dash)."""
    page = [(i, word) for i, word in enumerate(expected) if word["key"]]
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
                if same_word(word, said[j][0]):
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
        if same_word(expected_text, word):
            return {"ok": True, "heard": word}
    guess = heard[0][0].strip(".,!?;:\"'") if heard else ""
    changes = pronounce.sound_changes(expected_text, guess) if guess else []
    return {"ok": False, "heard": guess, "tips": _tips(changes)}


def _tips(changes):
    """At most two things to listen for. A swapped sound says the most;
    a sound left out or added only matters when nothing was swapped."""
    swaps = [change for change in changes if change["kind"] == "swap"]
    return [pronounce.explain(change) for change in (swaps or changes)][:2]
