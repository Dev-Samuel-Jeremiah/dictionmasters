"""Fast local lookup for the project's IPA-Dict English UK dataset.

The tab-separated file is parsed once per process. All source symbols,
including stress and syllable markers, are retained; only wrappers and
spacing are normalized.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings

DICT_PATH = Path(settings.BASE_DIR) / "data" / "ipa" / "en_UK.txt"
IPA_DICT_INVALID_ENTRIES = 0


def _wrap(raw):
    text = unicodedata.normalize("NFC", str(raw or "")).strip()
    if not text or "\n" in text or "\r" in text:
        return ""
    if (text.startswith("/") and text.endswith("/")) or (
        text.startswith("[") and text.endswith("]")
    ):
        text = text[1:-1]
    elif text.startswith(("/", "[")) or text.endswith(("/", "]")):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return f"/{text}/" if text else ""


def parse_ipa_variants(raw):
    """Split IPA-Dict's comma-separated alternatives into slash-wrapped IPA."""
    text = str(raw or "").strip()
    if not text:
        return ()

    if text.startswith("/") and text.endswith("/"):
        alternatives = text[1:-1].split(",")
    else:
        wrapped = re.fullmatch(r"\s*(/[^/]+/)(?:\s*,\s*(/[^/]+/))*\s*", text)
        if wrapped:
            alternatives = re.findall(r"/([^/]+)/", text)
        else:
            alternatives = [text]

    values = []
    for alternative in alternatives:
        ipa = _wrap(alternative)
        if ipa and ipa not in values:
            values.append(ipa)
    return tuple(values)


@lru_cache(maxsize=1)
def load_ipa_dict():
    """Return ``casefolded word -> tuple of pronunciations`` from IPA-Dict."""
    global IPA_DICT_INVALID_ENTRIES
    entries = {}
    invalid_entries = 0
    IPA_DICT_INVALID_ENTRIES = 0
    try:
        handle = open(DICT_PATH, encoding="utf-8")
    except OSError:
        return entries

    with handle:
        for line in handle:
            word, separator, raw_ipa = line.rstrip("\r\n").partition("\t")
            if not separator:
                invalid_entries += 1
                continue
            word = unicodedata.normalize("NFKC", word).strip().casefold()
            if not word:
                invalid_entries += 1
                continue
            pronunciations = parse_ipa_variants(raw_ipa)
            if pronunciations:
                existing = list(entries.get(word, ()))
                existing.extend(ipa for ipa in pronunciations if ipa not in existing)
                entries[word] = tuple(existing)
            else:
                invalid_entries += 1
    IPA_DICT_INVALID_ENTRIES = invalid_entries
    return entries


def _entries():
    """Backward-compatible alias for the former cached loader."""
    return load_ipa_dict()


def get_ipa(word):
    """DictionMasters-style British IPA, retaining alternatives."""
    from .british_ipa import normalize_british_ipa

    normalized = unicodedata.normalize("NFKC", str(word or "")).strip().casefold()
    pronunciations = (
        normalize_british_ipa(ipa, source="ipa_dict")
        for ipa in load_ipa_dict().get(normalized, ())
    )
    return ", ".join(ipa for ipa in pronunciations if ipa)
