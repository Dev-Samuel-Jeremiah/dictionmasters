"""
Phonemic transcriptions for Quick Words, from IPA-Dict UK.

A word's transcription used to be one more thing asked of the model
alongside its definition and example sentence — and a model asked to
transcribe pronunciation happily invents or misremembers one, symbol
by symbol, with nothing to check it against. IPA-Dict UK
(https://github.com/open-dict-data/ipa-dict) is a fixed, human-curated
list of British English words and their IPA instead: the model is
never asked for pronunciation at all, only this file is.

The file (data/ipa/en_UK.txt) is a tab-separated word/transcription
pair per line, occasionally with more than one transcription separated
by commas ("the\t/ðə, ði/") — the first is the one Quick Words shows.
It is loaded once per process and kept in memory: 65k short lines is
small, and every look-up after the first is then a dict hit.
"""

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

DICT_PATH = Path(settings.BASE_DIR) / "data" / "ipa" / "en_UK.txt"

# IPA-Dict UK spellings of a symbol -> the symbol the site's own
# phonemic chart uses, so a learner never meets a different alphabet
# in Quick Words than on the chart.
IPA_EQUIVALENTS = {
    "ɡ": "g",   # script g
    "ɛ": "e",   # DRESS
    "ɹ": "r",
}
# Syllable boundaries and linking marks — not part of the chart.
IPA_DROP = re.compile(r"[.‿]")


def _normalise(raw):
    text = str(raw or "").strip().strip("/[]").strip()
    for dict_symbol, chart_symbol in IPA_EQUIVALENTS.items():
        text = text.replace(dict_symbol, chart_symbol)
    text = IPA_DROP.sub("", text)
    text = re.sub(r"\s+", "", text)
    return f"/{text}/" if text else ""


@lru_cache(maxsize=1)
def _entries():
    """word (lowercase) -> chart-normalised transcription, built once."""
    entries = {}
    try:
        handle = open(DICT_PATH, encoding="utf-8")
    except OSError:
        return entries

    with handle:
        for line in handle:
            word, _, raw_ipa = line.partition("\t")
            word = word.strip().lower()
            if not word:
                continue
            first_pronunciation, _, _ = raw_ipa.partition(",")
            ipa = _normalise(first_pronunciation)
            if ipa:
                # A word already seen wins — first entry in the file stands.
                entries.setdefault(word, ipa)
    return entries


def get_ipa(word):
    """The chart-normalised transcription for `word`, or "" if IPA-Dict
    UK doesn't have an entry for it."""
    return _entries().get(str(word or "").strip().lower(), "")