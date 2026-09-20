"""
How words sound in British English — and where an American reading differs.

Everything the tutor teaches is Received Pronunciation, the accent on the
site's own phonemic chart. Pronunciations come from espeak-ng's RP voice,
which knows any word, including Nigerian names the dictionaries don't have.

Two jobs:

  * Judging what was heard. The tutor hears the reader through a
    transcriber, which writes down real words, so "tink" for "think" comes
    back as "tink" or "thing". Comparing how the two *sound* in RP tells
    the tutor that "there" read for "their" is no mistake at all (the same
    sound, the transcriber's choice of spelling), and, when they really do
    differ, which sound changed — the TH said as T, a final S left off.

  * Keeping to British. The same word is also looked up in the American
    voice. Where the two differ in a way a learner can act on — "dance"
    with the flat American A, "water" with the American D-sounding T,
    "new" without its Y — the word is one for the tutor to model in
    British. The wholesale differences of the accent (the R sounded at the
    end of "car", the American O in "go") are taught as patterns rather
    than marked on every other word.
"""

import re
import subprocess
import threading

RP_VOICE = "en-gb-x-rp"
US_VOICE = "en-us"
TIMEOUT = 10

# Symbols espeak writes that the phonemic chart writes differently.
TIDY = {"ɛ": "e", "ɐ": "ə", "ɹ": "r", "ᵻ": "ɪ", "ɡ": "g", "ɚ": "ər", "ʔ": "", "-": "", "_": ""}

# Every sound of English, longest first so "tʃ" is read as one sound, with
# a word that has it — so the tutor can say "/θ/ as in ‘think’".
SOUNDS = [
    ("tʃ", "chair"), ("dʒ", "jam"), ("aɪ", "my"), ("eɪ", "day"), ("ɔɪ", "boy"),
    ("əʊ", "go"), ("aʊ", "now"), ("ɪə", "near"), ("eə", "square"), ("ʊə", "cure"),
    ("iː", "see"), ("uː", "food"), ("ɑː", "car"), ("ɔː", "law"), ("ɜː", "bird"),
    ("θ", "think"), ("ð", "this"), ("ʃ", "shop"), ("ʒ", "measure"), ("ŋ", "sing"),
    ("æ", "cat"), ("ɒ", "hot"), ("ʌ", "cup"), ("ʊ", "book"), ("ɪ", "sit"),
    ("e", "bed"), ("ə", "about"), ("j", "yes"), ("w", "wet"), ("r", "red"),
    ("l", "leg"), ("m", "man"), ("n", "no"), ("h", "hat"), ("p", "pen"),
    ("b", "bag"), ("t", "ten"), ("d", "dog"), ("k", "cat"), ("g", "go"),
    ("f", "fan"), ("v", "van"), ("s", "sun"), ("z", "zoo"), ("i", "happy"),
    ("u", "to"), ("o", "law"), ("a", "cat"),
    # Sounds only the American voice uses, so its words can be read too.
    ("oʊ", "go"), ("ɑ", "car"), ("ɔ", "law"), ("ɾ", "ten"),
]
EXAMPLE = dict(SOUNDS)
# Longest first, so "oʊ" is never read as "o" followed by "ʊ".
SYMBOLS = sorted((symbol for symbol, _example in SOUNDS), key=len, reverse=True)
VOWELS = set("aeiouæɒʌʊɪəɜɔɑ") | {"aɪ", "eɪ", "ɔɪ", "əʊ", "oʊ", "aʊ", "ɪə", "eə", "ʊə",
                                   "iː", "uː", "ɑː", "ɔː", "ɜː"}

_said = {}
_lock = threading.Lock()


def _ask_espeak(words, voice):
    """{word: "wˈɔːtə"} — one call for the whole list."""
    try:
        done = subprocess.run(
            ["espeak-ng", "-v", voice, "-q", "--ipa"],
            input="\n".join(words), capture_output=True, text=True, timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return {}
    lines = done.stdout.split("\n")
    found = {}
    for word, line in zip(words, lines):
        text = line.strip()
        for espeak_symbol, ours in TIDY.items():
            text = text.replace(espeak_symbol, ours)
        found[word] = text
    return found


def _plain(word):
    return re.sub(r"[^a-z'-]", "", str(word or "").lower().replace("’", "'")).strip("'-")


def say(words, voice=RP_VOICE):
    """How each word is said, with stress marks: {"water": "wˈɔːtə"}.
    Looked up once per word per process."""
    words = [_plain(word) for word in words]
    wanted = []
    for word in words:
        if word and (word, voice) not in _said and word not in wanted:
            wanted.append(word)
    if wanted:
        found = _ask_espeak(wanted, voice)
        with _lock:
            for word in wanted:
                _said[(word, voice)] = found.get(word, "")
    return {word: _said.get((word, voice), "") for word in words if word}


def spoken(word, voice=RP_VOICE):
    return say([word], voice).get(_plain(word), "")


def split(text):
    """"wˈɔːtə" → ("w", "ɔː", "t", "ə"), stress marks dropped."""
    text = re.sub(r"[ˈˌ ]", "", str(text or ""))
    sounds, at = [], 0
    while at < len(text):
        for symbol in SYMBOLS:
            if text.startswith(symbol, at):
                sounds.append(symbol)
                at += len(symbol)
                break
        else:
            at += 1        # a symbol we don't teach; pass over it
    return tuple(sounds)


def sounds(word, voice=RP_VOICE):
    """The sounds of `word` in British English."""
    return split(spoken(word, voice))


def transcription(word):
    """The word as the phonemic chart would write it: "/wɔːtə/"."""
    found = sounds(word)
    return "/" + "".join(found) + "/" if found else ""


def sound_alike(one, other):
    """True when the two words are said exactly the same way ("their" and
    "there", "father" and "farther" — both of them in British English)."""
    mine = sounds(one)
    return bool(mine) and mine == sounds(other)


def describe(sound):
    example = EXAMPLE.get(sound, "")
    return f"/{sound}/ as in ‘{example}’" if example else f"/{sound}/"


def sound_changes(expected, heard):
    """What changed between the word on the page and the word heard, as
    [{"kind": "swap"|"missing"|"extra", "expected": "θ", "heard": "t"}]."""
    from difflib import SequenceMatcher

    ours, theirs = sounds(expected), sounds(heard)
    if not ours or not theirs:
        return []
    changes = []
    for op, a1, a2, b1, b2 in SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes():
        if op == "replace":
            for index in range(max(a2 - a1, b2 - b1)):
                want = ours[a1 + index] if a1 + index < a2 else ""
                got = theirs[b1 + index] if b1 + index < b2 else ""
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


def explain(change):
    """A change in words a learner understands."""
    want, got = change["expected"], change["heard"]
    if change["kind"] == "swap":
        return f"{describe(want)} came out as /{got}/"
    if change["kind"] == "missing":
        return f"the {describe(want)} sound was left out"
    return f"an extra /{got}/ sound crept in"


def patterns(changes):
    """The slips worth counting across a whole reading, as ("θ", "t") for a
    swap and ("s", "") for a sound left out. The same slip in five words is
    one thing to practise."""
    found = []
    for change in changes:
        want, got = change["expected"], change["heard"]
        if change["kind"] == "swap":
            found.append((want, got))
        elif change["kind"] == "missing":
            found.append((want, ""))
    return found


def pattern_label(want, got):
    example = EXAMPLE.get(want, "")
    where = f" (as in ‘{example}’)" if example else ""
    return f"/{want}/{where} said as /{got}/" if got else f"/{want}/{where} left out"


# ---------------------------------------------------------------------------
# British against American
# ---------------------------------------------------------------------------

# Words whose two pronunciations differ only because they are being said in
# a different accent, not because the word itself is said differently.
_NEUTRAL = [("r", ""), ("ɚ", "ə"), ("ː", ""), ("oʊ", "əʊ"), ("eə", "e"), ("ɪə", "ɪ"),
            ("ʊə", "ʊ"), ("ɑ", "ɒ"), ("ɔ", "ɒ"), ("o", "ɒ"), ("ʌ", "ɒ"), ("æ", "a"), ("i", "ɪ")]
_WEAK = {"i", "ɪ", "e", "ə", "ʊ", "u", "a", "ɒ"}

# What a learner can do something about, in the order the tutor says it.
KIND_LABELS = {
    "bath": "the British ‘ah’ sound",
    "yod": "the Y sound after the first letter",
    "flap": "a clear T, not a D sound",
    "lexical": "a different British pronunciation",
}


def _flatten(text):
    """A pronunciation with the accent's own system taken out: the R that
    only Americans sound, their O in "go", and every unstressed vowel,
    which both accents blur."""
    text = re.sub(r"[ˌ ]", "", str(text or ""))
    # Keep only the vowel right after the stress mark as itself.
    out, stressed_done, at = [], False, 0
    pieces = text.split("ˈ")
    for number, piece in enumerate(pieces):
        for sound in split(piece):
            if sound not in VOWELS:
                out.append(sound)
                continue
            flat = sound
            for a, b in _NEUTRAL:
                flat = flat.replace(a, b)
            if number > 0 and not stressed_done:
                stressed_done = True       # the stressed vowel keeps its colour
                out.append(flat)
            else:
                out.append("ə" if flat in _WEAK else flat)
        stressed_done = stressed_done or number > 0
    flat = "".join(out)
    for a, b in _NEUTRAL:
        flat = flat.replace(a, b)
    return flat


def _stressed(text):
    """The vowel the stress falls on — where "tomato" and "vitamin" really
    part company with their American readings."""
    after = str(text or "").split("ˈ")
    if len(after) < 2:
        return ""
    for sound in split(after[1]):
        if sound in VOWELS:
            flat = sound
            for a, b in _NEUTRAL:
                flat = flat.replace(a, b)
            return flat
    return ""


def american_difference(word):
    """How an American would say `word` differently, or None when the
    difference is only the accent's own system (the sounded R, the
    American O), which is taught as a pattern instead.

    Returns {"kind": "bath"|"yod"|"flap"|"lexical", "british": "/dɑːns/",
    "american": "/dæns/"}."""
    word = _plain(word)
    if not word or len(word) < 2:
        return None
    rp, us = spoken(word, RP_VOICE), spoken(word, US_VOICE)
    if not rp or not us or rp == us:
        return None
    if _flatten(rp) == _flatten(us):
        return None

    bare_rp, bare_us = re.sub(r"[ˈˌ ]", "", rp), re.sub(r"[ˈˌ ]", "", us)
    # The R only Americans sound is part of the accent, not the word, so
    # it is taken out before asking what kind of difference this is.
    dry_rp, dry_us = bare_rp.replace("r", ""), bare_us.replace("r", "")
    if "ɑː" in dry_rp and "æ" in dry_us and dry_rp.replace("ɑː", "æ") == dry_us:
        kind = "bath"          # dance, bath, class, after
    elif "j" in bare_rp and "j" not in bare_us:
        kind = "yod"           # new, tune, duty, news
    elif _stressed(rp) != _stressed(us):
        kind = "lexical"       # a different vowel where the stress falls
    elif "ɾ" in bare_us and "t" in bare_rp:
        kind = "flap"
    else:
        kind = "lexical"
    return {
        "kind": kind,
        "british": "/" + "".join(split(rp)) + "/",
        "american": "/" + re.sub(r"r{2,}", "r", "".join(split(bare_us.replace("ɾ", "d")))) + "/",
        "note": KIND_LABELS[kind],
    }


def british_words(words):
    """Which of `words` an American would say differently enough to be
    worth modelling: {index: difference}. Looked up in one go."""
    say([word for word in words])          # warm both voices in two calls
    say([word for word in words], US_VOICE)
    found = {}
    for index, word in enumerate(words):
        difference = american_difference(word)
        if difference:
            found[index] = difference
    return found
