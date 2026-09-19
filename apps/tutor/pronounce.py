"""
How words sound, from the CMU Pronouncing Dictionary.

The tutor hears the reader through a transcriber, which writes down real
words. So "tink" for "think" comes back as "tink" or "thing", and "bag"
for "back" comes back as "bag". Comparing how the two *sound* tells the
tutor two things a spelling check can't:

  * words that sound the same are the same to a listener — "there" read
    for "their" is not a mistake, only the transcriber's spelling;
  * when they differ, which sound changed — the TH said as T, the V said
    as B, a final S left off — which is what a learner can practise.

The dictionary (data/cmudict.txt, built from CMUdict; licence beside it)
is one line per word, "word<TAB>PH ON ES|VARIANT", sorted. It's read once
per process into a list and searched by halving, which costs a few MB
rather than the fifty a full dictionary of Python objects would.
"""

import bisect
import os
import re
import threading
from difflib import SequenceMatcher

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "cmudict.txt")

_lines = None
_keys = None
_lock = threading.Lock()


def _load():
    global _lines, _keys
    if _lines is None:
        with _lock:
            if _lines is None:
                with open(DATA_FILE, encoding="utf-8") as handle:
                    lines = handle.read().splitlines()
                _keys = [line.split("\t", 1)[0] for line in lines]
                _lines = lines
    return _keys, _lines


def _plain(word):
    return re.sub(r"[^a-z']", "", str(word).lower().replace("’", "'")).strip("'")


def pronunciations(word):
    """Every way `word` is said, each a tuple of ARPAbet sounds without
    stress — ("TH", "IH", "NG", "K") — or [] if the dictionary hasn't it."""
    word = _plain(word)
    if not word:
        return []
    keys, lines = _load()
    at = bisect.bisect_left(keys, word)
    if at < len(keys) and keys[at] == word:
        return [tuple(variant.split()) for variant in lines[at].split("\t", 1)[1].split("|")]
    return []


def known(word):
    return bool(pronunciations(word))


def sound_alike(expected, heard):
    """True when the two words can be said exactly the same way."""
    ours = set(pronunciations(expected))
    return bool(ours) and bool(ours & set(pronunciations(heard)))


# ---------------------------------------------------------------------------
# Naming the sounds
# ---------------------------------------------------------------------------

# ARPAbet → the symbols on the site's phonemic chart, with a word that has
# the sound, so the feedback reads "the /θ/ sound in ‘think’".
SOUNDS = {
    "IY": ("iː", "see"), "IH": ("ɪ", "sit"), "EH": ("e", "bed"), "AE": ("æ", "cat"),
    "AA": ("ɑː", "car"), "AH": ("ʌ", "cup"), "AO": ("ɔː", "law"), "UH": ("ʊ", "book"),
    "UW": ("uː", "food"), "ER": ("ɜː", "bird"), "EY": ("eɪ", "day"), "AY": ("aɪ", "my"),
    "OY": ("ɔɪ", "boy"), "AW": ("aʊ", "now"), "OW": ("əʊ", "go"),
    "P": ("p", "pen"), "B": ("b", "bag"), "T": ("t", "ten"), "D": ("d", "dog"),
    "K": ("k", "cat"), "G": ("g", "go"), "CH": ("tʃ", "chair"), "JH": ("dʒ", "jam"),
    "F": ("f", "fan"), "V": ("v", "van"), "TH": ("θ", "think"), "DH": ("ð", "this"),
    "S": ("s", "sun"), "Z": ("z", "zoo"), "SH": ("ʃ", "shop"), "ZH": ("ʒ", "measure"),
    "HH": ("h", "hat"), "M": ("m", "man"), "N": ("n", "no"), "NG": ("ŋ", "sing"),
    "L": ("l", "leg"), "R": ("r", "red"), "W": ("w", "wet"), "Y": ("j", "yes"),
}


def symbol(sound):
    return SOUNDS.get(sound, (sound.lower(), ""))[0]


def describe(sound):
    ipa, example = SOUNDS.get(sound, (sound.lower(), ""))
    return f"/{ipa}/ as in ‘{example}’" if example else f"/{ipa}/"


def sound_changes(expected, heard):
    """What changed between the word on the page and the word heard, as
    [{"kind": "swap"|"missing"|"extra", "expected": "TH", "heard": "T"}].

    The closest pair of pronunciations is compared sound by sound. Empty
    when either word isn't in the dictionary (a name, say) — the tutor
    then just models the word without naming a sound."""
    best, best_score = None, -1.0
    for ours in pronunciations(expected):
        for theirs in pronunciations(heard):
            score = SequenceMatcher(None, ours, theirs, autojunk=False).ratio()
            if score > best_score:
                best, best_score = (ours, theirs), score
    if best is None:
        return []
    # British English drops the R the dictionary writes after a vowel
    # ("brother", "car"), so R is left out of the comparison altogether.
    ours, theirs = (tuple(sound for sound in side if sound != "R") for side in best)
    changes = []
    for op, a1, a2, b1, b2 in SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes():
        if op == "replace":
            for index in range(max(a2 - a1, b2 - b1)):
                want = ours[a1 + index] if a1 + index < a2 else None
                got = theirs[b1 + index] if b1 + index < b2 else None
                if want and got:
                    changes.append({"kind": "swap", "expected": want, "heard": got})
                elif want:
                    changes.append({"kind": "missing", "expected": want, "heard": ""})
                else:
                    changes.append({"kind": "extra", "expected": "", "heard": got})
        elif op == "delete":
            changes += [{"kind": "missing", "expected": sound, "heard": ""} for sound in ours[a1:a2]]
        elif op == "insert":
            changes += [{"kind": "extra", "expected": "", "heard": sound} for sound in theirs[b1:b2]]
    return changes


VOWELS = {"IY", "IH", "EH", "AE", "AA", "AH", "AO", "UH", "UW", "ER", "EY", "AY", "OY", "AW", "OW"}


def explain(change):
    """A change in words a learner understands.

    The dictionary is American, and British vowels differ from it in
    places ("dance", "car"), so a vowel is only ever called "the vowel";
    consonants — the TH, the V, a final S — are named exactly."""
    want, got = change["expected"], change["heard"]
    if change["kind"] == "swap":
        if want in VOWELS and got in VOWELS:
            return "the vowel sound was different"
        if want in VOWELS or got in VOWELS:
            return "one sound was changed"
        return f"{describe(want)} came out as /{symbol(got)}/"
    if change["kind"] == "missing":
        if want in VOWELS:
            return "a vowel sound was left out"
        ipa, example = SOUNDS.get(want, (want.lower(), ""))
        return f"the /{ipa}/ sound (as in ‘{example}’) was left out"
    return "an extra vowel sound crept in" if got in VOWELS else f"an extra /{symbol(got)}/ sound crept in"


def patterns(changes):
    """The consonant slips among `changes`, as ("TH", "T") for a swap and
    ("S", "") for a sound left out — what is worth counting across a whole
    reading, since the same slip in five words is one thing to practise."""
    found = []
    for change in changes:
        want, got = change["expected"], change["heard"]
        if change["kind"] == "swap" and want not in VOWELS and got not in VOWELS:
            found.append((want, got))
        elif change["kind"] == "missing" and want not in VOWELS:
            found.append((want, ""))
    return found


def pattern_label(want, got):
    """("TH", "T") → "/θ/ (as in ‘think’) said as /t/"."""
    ipa, example = SOUNDS.get(want, (want.lower(), ""))
    if got:
        return f"/{ipa}/ (as in ‘{example}’) said as /{symbol(got)}/"
    return f"/{ipa}/ (as in ‘{example}’) left out"
