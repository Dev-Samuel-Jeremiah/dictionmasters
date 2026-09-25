"""
Building a question from a Quick Word.

Every choice in here is seeded, so the same match seed and round number
always produce the same question — which is what will let a friend's
challenge or a daily clash give everyone identical questions later.

The wrong answers are where the teaching is. On the harder tiers a
transcription's distractors are the mistakes Nigerian learners actually
make — TH said as T or D, V as B, a long vowel cut short — so choosing
correctly means hearing the difference, not guessing.
"""

import random
import re

from apps.accounts.access import limit_to_levels
from apps.manage.rich_text import plain_text
from apps.quick_words.models import QuickWord

from . import catalogue as C

# One substitution per rule, each turning the correct transcription into
# a common mispronunciation. Longer symbols come first so /iː/ isn't
# caught by a rule meant for /ɪ/.
TRAP_SUBSTITUTIONS = [
    ("θ", "t"), ("ð", "d"), ("v", "b"),
    ("iː", "ɪ"), ("uː", "ʊ"), ("ɜː", "e"), ("ɔː", "ɒ"), ("ɑː", "a"),
    ("əʊ", "o"), ("eɪ", "e"),
    ("ɪ", "iː"), ("ʊ", "uː"), ("ʌ", "ɔ"), ("æ", "a"), ("ə", "a"),
    ("ʒ", "ʃ"), ("z", "s"), ("ŋ", "n"),
]

BLANK = "_____"


def word_pool(tier, user=None):
    """The words a tier draws on — ones complete enough to build any
    question from. A thin tier borrows from the whole library.

    A school's teachers and students play with their own level's words,
    the same ones they study."""
    usable = QuickWord.objects.filter(is_published=True).exclude(definition="").exclude(ipa="")
    if user is not None:
        usable = limit_to_levels(usable, user)
    tiered = usable.filter(level__in=tier.levels)
    words = list(tiered if tiered.count() >= C.MIN_POOL else usable)
    for word in words:
        # Rounds use these as one-line prompts, options and answers, so the
        # editor's formatting is dropped (the instances are never saved).
        word.definition = " ".join(plain_text(word.definition).split())
        word.example_sentence = " ".join(plain_text(word.example_sentence).split())
    return words


def has_audio(word):
    return bool(word.audio_file or word.audio_url)


# ---------------------------------------------------------------------------
# Wrong answers
# ---------------------------------------------------------------------------

def trap_transcriptions(ipa, rng, count=3):
    core = ipa.strip().strip("/")
    variants = []
    rules = TRAP_SUBSTITUTIONS[:]
    rng.shuffle(rules)
    for source, target in rules:
        if source in core:
            variant = f"/{core.replace(source, target)}/"
            if variant != f"/{core}/" and variant not in variants:
                variants.append(variant)
        if len(variants) == count:
            break
    return variants


def misspellings(word, rng, library, count=3):
    """Believable wrong spellings — never one that is itself a real word
    in the library (THEIR is not a misspelling of THERE)."""
    w = word.lower()
    candidates = set()

    if "ie" in w:
        candidates.add(w.replace("ie", "ei", 1))
    if "ei" in w:
        candidates.add(w.replace("ei", "ie", 1))
    for a, b in (("ph", "f"), ("kn", "n"), ("wr", "r"), ("mb", "m"), ("ck", "k"), ("ce", "se"), ("ci", "si")):
        if a in w:
            candidates.add(w.replace(a, b, 1))

    for i in range(1, len(w)):
        if w[i] == w[i - 1] and w[i].isalpha():
            candidates.add(w[:i] + w[i + 1:])                 # undouble: "commit" -> "comit"
    for i in range(1, len(w) - 1):
        if w[i] not in "aeiou" and w[i - 1] in "aeiou" and w[i + 1] in "aeiou":
            candidates.add(w[:i] + w[i] + w[i:])              # double: "later" -> "latter"

    swaps = {"a": "e", "e": "i", "i": "e", "o": "u", "u": "o"}
    for i, ch in enumerate(w):
        if i and ch in swaps:
            candidates.add(w[:i] + swaps[ch] + w[i + 1:])
    for i in range(1, len(w) - 1):
        candidates.add(w[:i] + w[i + 1:])                     # drop one letter

    real_words = {entry.word.lower() for entry in library}
    usable = sorted(c for c in candidates if c != w and c not in real_words and len(c) >= 2)
    rng.shuffle(usable)
    return usable[:count]


def scramble(word, rng):
    letters = list(word.lower())
    for _ in range(10):
        rng.shuffle(letters)
        if "".join(letters) != word.lower():
            break
    return "".join(letters).upper()


def gap_sentence(word, sentence):
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    if not pattern.search(sentence or ""):
        return None
    return pattern.sub(BLANK, sentence, count=1)


def other_words(word, library, tier, rng, count=3):
    """Words to offer beside the right one. On the harder tiers they look
    like the answer — similar length, often the same first letter."""
    others = [w for w in library if w.pk != word.pk and w.word.lower() != word.word.lower()]
    if tier.distractors == "near":
        others.sort(key=lambda w: (
            abs(len(w.word) - len(word.word)),
            w.word[:1].lower() != word.word[:1].lower(),
            rng.random(),
        ))
        return others[:count]
    rng.shuffle(others)
    return others[:count]


# ---------------------------------------------------------------------------
# Building one question
# ---------------------------------------------------------------------------

def _choice(rng, answer, wrong):
    options = [answer] + wrong
    rng.shuffle(options)
    return options


def _build(kind, word, library, tier, rng):
    """The round's fields for this kind of question, or None if the word
    can't support it (no audio, no example sentence, too few look-alikes)."""
    distract = other_words(word, library, tier, rng)

    if kind == C.MEANING_TO_WORD:
        if len(distract) < 3:
            return None
        return {"prompt": word.definition, "answer": word.word,
                "options": _choice(rng, word.word, [w.word for w in distract])}

    if kind == C.WORD_TO_MEANING:
        meanings = list(dict.fromkeys(w.definition for w in distract if w.definition != word.definition))
        if len(meanings) < 3:
            return None
        return {"prompt": word.word, "prompt_detail": word.ipa, "answer": word.definition,
                "options": _choice(rng, word.definition, meanings[:3])}

    if kind == C.FILL_GAP:
        sentence = gap_sentence(word.word, word.example_sentence)
        if not sentence or len(distract) < 3:
            return None
        return {"prompt": sentence, "prompt_detail": word.definition, "answer": word.word,
                "options": _choice(rng, word.word, [w.word for w in distract])}

    if kind == C.IPA_TO_WORD:
        if len(distract) < 3:
            return None
        return {"prompt": word.ipa, "answer": word.word,
                "options": _choice(rng, word.word, [w.word for w in distract])}

    if kind == C.WORD_TO_IPA:
        wrong = trap_transcriptions(word.ipa, rng) if tier.distractors == "near" else []
        for other in distract:                      # top up with real transcriptions
            if len(wrong) == 3:
                break
            if other.ipa and other.ipa != word.ipa and other.ipa not in wrong:
                wrong.append(other.ipa)
        if len(wrong) < 3:
            return None
        return {"prompt": word.word, "answer": word.ipa, "options": _choice(rng, word.ipa, wrong[:3])}

    if kind == C.MISSPELLING:
        wrong = misspellings(word.word, rng, library)
        if len(word.word) < 4 or len(wrong) < 3:
            return None
        return {"prompt": word.definition, "answer": word.word.lower(),
                "options": _choice(rng, word.word.lower(), wrong)}

    if kind == C.UNSCRAMBLE:
        if len(word.word) < 3 or " " in word.word:
            return None
        return {"prompt": scramble(word.word, rng), "prompt_detail": word.definition, "answer": word.word}

    if kind == C.HEAR_CHOOSE:
        if not has_audio(word) or len(distract) < 3:
            return None
        return {"answer": word.word, "options": _choice(rng, word.word, [w.word for w in distract])}

    if kind == C.HEAR_SPELL:
        if not has_audio(word):
            return None
        return {"prompt_detail": word.definition, "answer": word.word}

    return None


def build_round(match, number, used_word_ids):
    """Fields for the next round of a match: a word it hasn't used yet,
    asked in a way that word can support."""
    tier = match.tier
    rng = random.Random(f"{match.seed}:{number}")
    library = word_pool(tier, match.user)

    fresh = [w for w in library if w.pk not in used_word_ids]
    candidates = fresh or library[:]          # every word used: start again
    rng.shuffle(candidates)

    for word in candidates[:40]:
        kinds = list(tier.types)
        rng.shuffle(kinds)
        for kind in kinds:
            fields = _build(kind, word, library, tier, rng)
            if fields:
                return {"kind": kind, "word": word, "prompt": "", "prompt_detail": "", "options": [], **fields}
    return None


def library_ready(tier, user=None):
    """Whether there are enough words to play this tier at all."""
    return len(word_pool(tier, user)) >= 4
