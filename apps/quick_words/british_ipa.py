"""British English IPA lookup for Quick Words.

Lookup order is intentionally fixed: Britfone, IPA-Dict UK, a saved
QuickWord pronunciation, then a narrowly validated OpenAI fallback.
The bundled dictionaries are parsed once per process and held in memory.
"""

import logging
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError

from .ipa_dict import load_ipa_dict

logger = logging.getLogger(__name__)

BRITFONE_PATH = Path(settings.BASE_DIR) / "data" / "ipa" / "britfone" / "britfone.main.3.0.1.csv"
ACCENT = "en-GB"
MAX_IPA_LENGTH = 500
AI_CACHE_SECONDS = 300
BRITFONE_INVALID_ENTRIES = 0


def normalize_word(word):
    """Normalize a lookup key while preserving meaningful punctuation."""
    text = unicodedata.normalize("NFKC", str(word or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


# Explicit onset clusters used only to place Britfone/IPADict stress marks
# before the stressed syllable, the convention used by the site's learner
# chart and existing QuickWord entries.
_SINGLE_ONSETS = set("ptkbdgmnŋfvθðszʃʒhɹrjlwʔx")
_ONSET_CLUSTERS = {
    "bl", "br", "dr", "dw", "fl", "fr", "gl", "gr", "kl", "kr",
    "kw", "pl", "pr", "sl", "sm", "sn", "sp", "st", "sk", "sw",
    "tr", "tw", "θr", "spl", "spr", "str", "skr", "skw", "stj",
    "spj", "blj", "brj", "plj", "prj", "klj", "krj", "flj", "frj",
    "pj", "bj", "tj", "dj", "kj", "gj", "fj", "vj", "mj", "nj",
    "sj", "zj",
}
_VOWEL_SYMBOLS = set("aeiouæɑɒɔɛɜɐəɪʊʌɨʉɘɵɤɚɝøœɶɞ")


def _last_vowel_end(text):
    """Index after the last vowel (and its length mark) in a prefix."""
    last_end = None
    index = 0
    while index < len(text):
        if text[index] in _VOWEL_SYMBOLS:
            last_end = index + 1
            index += 1
            while index < len(text) and (
                text[index] in {"ː", "ˑ"} or unicodedata.category(text[index]).startswith("M")
            ):
                last_end = index + 1
                index += 1
        else:
            index += 1
    return last_end


def _traditional_stress_position(text):
    """Move vowel-attached stress to a known syllable onset when safe."""
    for match in reversed(list(re.finditer(r"[ˈˌ]", text))):
        index = match.start()
        prefix = text[:index]
        vowel_end = _last_vowel_end(prefix)
        cluster_start = vowel_end if vowel_end is not None else 0
        cluster = prefix[cluster_start:]
        if not cluster or any(char in "ˈˌ.‿|" for char in cluster):
            continue

        onset = ""
        for length in range(len(cluster), 0, -1):
            candidate = cluster[-length:]
            if candidate in _ONSET_CLUSTERS or (length == 1 and candidate in _SINGLE_ONSETS):
                onset = candidate
                break
        if onset:
            new_index = index - len(onset)
            text = text[:new_index] + match.group() + text[new_index:index] + text[index + 1:]
    return text


def normalize_british_ipa(ipa: str, source=None) -> str:
    """Normalize IPA wrappers and documented source notation differences.

    With no ``source``, this only applies NFC, matching brackets/slashes,
    and whitespace cleanup. For Britfone, its README explicitly documents
    strict /ɐ ɹ ɛ/ where traditional English-learning notation uses /ʌ r e/;
    those source-specific equivalences are applied. IPA-Dict and AI output
    map script-g /ɡ/ to the site's /g/, /ɹ/ to its traditional /r/, and /ɛ/
    to its chart's /e/. IPA-Dict's unstressed /ɐ/ is rendered /ə/ (a directly
    stressed /ɐ/ becomes /ʌ/). No length, diphthong, consonant, or vowel
    contrast is changed beyond those documented symbol conventions. Known
    stress marks are moved from the stressed vowel to its legal syllable
    onset; if the onset is ambiguous, the source position is retained.
    """
    text = unicodedata.normalize("NFC", str(ipa or "")).strip()
    if not text or "\n" in text or "\r" in text:
        return ""

    if (text.startswith("/") and text.endswith("/")) or (
        text.startswith("[") and text.endswith("]")
    ):
        text = text[1:-1]
    elif text.startswith(("/", "[")) or text.endswith(("/", "]")):
        return ""

    text = re.sub(r"\s+", " ", text).strip()
    if source == "britfone":
        text = text.replace("ɐ", "ʌ").replace("ɹ", "r").replace("ɛ", "e").replace("ɡ", "g")
    elif source in {"ipa_dict", "openai"}:
        text = text.replace("ɡ", "g").replace("ɹ", "r").replace("ɛ", "e")
        text = re.sub(r"([ˈˌ])ɐ", r"\1ʌ", text).replace("ɐ", "ə")

    if source in {"britfone", "ipa_dict", "openai"}:
        text = _traditional_stress_position(text)
    if not text or len(text) > MAX_IPA_LENGTH:
        return ""
    return f"/{text}/"


def _is_reasonable_dictionary_ipa(ipa):
    if not ipa or len(ipa) > MAX_IPA_LENGTH or "\n" in ipa or "\r" in ipa:
        return False
    body = ipa[1:-1] if ipa.startswith("/") and ipa.endswith("/") else ""
    if not body or any(token in body.casefold() for token in ("pronunciation", "british english", "json")):
        return False
    return not any(char in "{}<>" for char in body)


def _britfone_key(raw_word):
    """Strip Britfone's numbered pronunciation suffix, if present."""
    return re.sub(r"\(\d+\)$", "", raw_word.strip())


@lru_cache(maxsize=1)
def load_britfone():
    """Return ``casefolded word -> tuple of slash-wrapped pronunciations``."""
    global BRITFONE_INVALID_ENTRIES
    entries = defaultdict(list)
    invalid_entries = 0
    BRITFONE_INVALID_ENTRIES = 0
    try:
        handle = open(BRITFONE_PATH, encoding="utf-8")
    except OSError:
        logger.exception("Could not read local Britfone dataset at %s", BRITFONE_PATH)
        return {}

    with handle:
        for line_number, line in enumerate(handle, start=1):
            raw_word, separator, raw_ipa = line.rstrip("\r\n").partition(",")
            if not separator:
                invalid_entries += 1
                logger.warning("Ignoring malformed Britfone row %d", line_number)
                continue
            word = normalize_word(_britfone_key(raw_word))
            if not word:
                invalid_entries += 1
                continue

            # Britfone separates IPA units with spaces. An underscore is its
            # documented word boundary marker, so retain that as a space.
            symbols = "".join(" " if unit == "_" else unit for unit in raw_ipa.split())
            ipa = normalize_british_ipa(symbols, source="britfone")
            if _is_reasonable_dictionary_ipa(ipa):
                if ipa not in entries[word]:
                    entries[word].append(ipa)
            else:
                invalid_entries += 1
    BRITFONE_INVALID_ENTRIES = invalid_entries
    return {word: tuple(prons) for word, prons in entries.items()}


def _result(word, pronunciations=(), source=None, confidence=None, review_required=True):
    pronunciations = tuple(pronunciations)
    return {
        "word": word,
        "ipa": ", ".join(pronunciations) if pronunciations else None,
        "pronunciations": list(pronunciations),
        "source": source,
        "confidence": confidence,
        "review_required": review_required,
        "accent": ACCENT,
    }


def _database_pronunciation(word):
    try:
        from .models import QuickWord

        record = (
            QuickWord.objects.filter(word__iexact=word)
            .exclude(ipa="")
            .order_by("pk")
            .first()
        )
    except DatabaseError:
        logger.exception("Database unavailable during British IPA lookup for %r", word)
        return None

    if record is None:
        return None

    from .ipa_dict import parse_ipa_variants

    pronunciations = tuple(
        ipa for ipa in (normalize_british_ipa(value) for value in parse_ipa_variants(record.ipa))
        if _is_reasonable_dictionary_ipa(ipa)
    )
    if not pronunciations:
        return None

    source = record.ipa_source or "database"
    confidence = record.ipa_confidence or "unknown"
    return _result(
        word,
        pronunciations,
        source=source,
        confidence=confidence,
        review_required=record.ipa_review_required or confidence in {"ai", "unknown"},
    )


def _valid_ai_ipa(raw):
    """Accept only slash-delimited IPA variants, never prose or JSON."""
    text = unicodedata.normalize("NFC", str(raw or "")).strip()
    if not text or len(text) > MAX_IPA_LENGTH or "\n" in text or "\r" in text:
        return ()

    match = re.fullmatch(r"\s*(/[^/\s]+/)(?:\s*,\s*(/[^/\s]+/))*\s*", text)
    if not match:
        return ()
    variants = re.findall(r"/([^/\s]+)/", text)
    if not variants or len(variants) > 8:
        return ()

    allowed_punctuation = set("ˈˌːˑ̥̬̆̈̃ʰʷʲˠˤ͜͡.‿|‖-()'0123456789")
    suspicious_words = {"british", "pronunciation", "transcription", "ipa", "json"}
    validated = []
    for body in variants:
        lowered = body.casefold()
        if any(word in lowered for word in suspicious_words):
            return ()
        if not any(ord(char) > 127 for char in body):
            # A wholly ASCII response is commonly an English spelling or
            # explanatory text, not the requested learner IPA.
            return ()
        if re.search(r"[ˈˌ]{2}|[ˈˌ]$", body):
            return ()
        if not any(char.isalpha() for char in body):
            return ()
        if any(
            not (char.isalpha() or unicodedata.category(char).startswith("M")
                 or char in allowed_punctuation)
            for char in body
        ):
            return ()
        rendered = normalize_british_ipa(f"/{body}/", source="openai")
        if not rendered:
            return ()
        validated.append(rendered)
    return tuple(validated)


def _ai_pronunciation(word):
    cache_key = f"quick-words-british-ipa-ai-v1:{word}"
    try:
        cached = cache.get(cache_key)
        if cached:
            return cached
    except Exception:
        logger.debug("IPA cache read failed", exc_info=True)

    try:
        # Lazy import avoids a module cycle: lookup.py uses this service too.
        from .lookup import LookupUnavailable, lookup_ipa_with_openai

        raw = lookup_ipa_with_openai(word)
    except (LookupUnavailable, OSError, ValueError) as error:
        logger.warning("OpenAI British IPA fallback failed for %r: %s", word, error)
        return None

    pronunciations = _valid_ai_ipa(raw)
    if not pronunciations:
        logger.warning("Rejected invalid AI IPA response for %r", word)
        return None

    result = _result(
        word, pronunciations, source="openai", confidence="ai", review_required=True
    )
    try:
        cache.set(cache_key, result, timeout=AI_CACHE_SECONDS)
    except Exception:
        logger.debug("IPA cache write failed", exc_info=True)
    return result


def get_british_ipa(word, *, allow_ai=True):
    """Get British IPA and provenance in priority order.

    The returned mapping always contains ``word``, ``ipa``,
    ``pronunciations``, ``source``, ``confidence``, ``review_required`` and
    ``accent``. Missing pronunciations have ``ipa/source/confidence=None``.
    """
    normalized = normalize_word(word)
    if not normalized:
        return _result(normalized)

    britfone = load_britfone().get(normalized, ())
    if britfone:
        return _result(normalized, britfone, "britfone", "dictionary", False)

    ipa_dict = tuple(
        normalize_british_ipa(ipa, source="ipa_dict")
        for ipa in load_ipa_dict().get(normalized, ())
    )
    ipa_dict = tuple(ipa for ipa in ipa_dict if _is_reasonable_dictionary_ipa(ipa))
    if ipa_dict:
        return _result(normalized, ipa_dict, "ipa_dict", "dictionary", False)

    database = _database_pronunciation(normalized)
    if database:
        return database

    if allow_ai:
        ai_result = _ai_pronunciation(normalized)
        if ai_result:
            return ai_result
    return _result(normalized)
