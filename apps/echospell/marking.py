"""
Marking for EchoSpell activities.

Everything a learner submits is marked here so that one rule set covers
every activity kind. Marking is deliberately forgiving about things
that are not being tested — case, stray punctuation, the slashes around
a transcription, doubled spaces — and strict about the thing that is:
a missing length mark really does turn "sheep" into "ship".

Recording activities return None rather than True/False: no code marks
those, a teacher does.
"""

import random
import re
import unicodedata

from .activity_kinds import (
    MODE_CHOICE,
    MODE_ORDER,
    MODE_RECORD,
    MODE_SORT,
    MODE_TYPED,
)

_PUNCTUATION_RE = re.compile(r"[.,!?;:\"“”‘’()\[\]]")
_WHITESPACE_RE = re.compile(r"\s+")
_IPA_WRAPPER_RE = re.compile(r"^[/\[]+|[/\]]+$")
# Primary and secondary stress: taught, but not what most of these
# exercises are testing, so a learner may leave them out.
_STRESS_RE = re.compile(r"[ˈˌ']")


def normalise(text):
    """Casefolded, de-punctuated, single-spaced — for ordinary words."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = _PUNCTUATION_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _ipa_forms(text):
    """The accepted spellings of one transcription: as written, and
    again without stress marks."""
    base = unicodedata.normalize("NFKC", str(text or "")).strip()
    base = _IPA_WRAPPER_RE.sub("", base.strip())
    base = _WHITESPACE_RE.sub("", base).casefold()
    return {base, _STRESS_RE.sub("", base)}


def alternatives(answer):
    """An answer may list equally correct forms separated by "|"."""
    return [part for part in str(answer or "").split("|") if part.strip()]


def answers_match(given, answer, *, transcription=False):
    """Whether `given` matches any accepted form of `answer`.

    The one comparison every marked answer on the site goes through —
    EchoSpell activities and assessments alike — so "correct" means the
    same thing everywhere.
    """
    given = str(given or "").strip()
    if not given:
        return False
    if transcription:
        given_forms = _ipa_forms(given)
        return any(given_forms & _ipa_forms(option) for option in alternatives(answer))
    given_n = normalise(given)
    return any(given_n == normalise(option) for option in alternatives(answer))


def grade_sentence_use(word, sentence):
    """Marks a "use this word in a sentence" answer.

    A stand-in for AI marking: it only checks the word was actually used
    and that there is a sentence around it. Swap the body for an AI call
    later — callers only read the (correct, feedback) pair.
    """
    text = str(sentence or "").strip()
    if not text:
        return False, "Write a sentence before checking it."

    word_l = str(word or "").strip().casefold()
    if word_l and not re.search(r"\b" + re.escape(word_l) + r"\b", text.casefold()):
        return False, f'Your sentence should use the word "{word}".'

    if len(text.split()) < 3:
        return False, "Try writing a full sentence, not just the word."

    return True, "Well done — that's a good sentence!"


def shuffled_tokens(sentence, seed):
    """The words of a sentence in a jumbled but stable order, so a
    learner who reloads the page does not get a different puzzle."""
    words = [w for w in str(sentence or "").split() if w]
    if len(words) < 2:
        return words
    rng = random.Random(seed)
    for _ in range(6):
        shuffled = words[:]
        rng.shuffle(shuffled)
        if shuffled != words:
            return shuffled
    return words


def mark_response(kind, item, given):
    """True, False, or None when only a teacher can mark it."""
    if kind is None or kind.mode == MODE_RECORD:
        return None

    given = str(given or "").strip()
    if not given:
        return False

    if kind.slug == "word-to-sentence":
        correct, _ = grade_sentence_use(item.prompt, given)
        return correct

    if kind.slug == "transcription":
        return answers_match(given, item.answer, transcription=True)

    if kind.mode in (MODE_TYPED, MODE_CHOICE, MODE_SORT, MODE_ORDER):
        return answers_match(given, item.answer)

    return None


def feedback_for(kind, item, given, is_correct):
    """One short line of learner-facing feedback per answer."""
    if is_correct is None:
        return "Sent to your teacher for marking."
    if is_correct:
        return "Correct"
    if kind is not None and kind.slug == "word-to-sentence":
        return grade_sentence_use(item.prompt, given)[1]
    if not str(given or "").strip():
        return "You left this one blank."
    return f"The answer is {item.first_answer}"
