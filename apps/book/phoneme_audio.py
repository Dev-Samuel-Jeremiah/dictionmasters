"""
Spoken audio for the phonemic chart, made with ElevenLabs.

Text-to-speech can't reliably say a sound on its own (a lone /p/ or /θ/
comes out as a letter name or a noise), so each recording says the
sound's keyword clearly, then the example words from its 44 Academy
lesson when there is one: "think. thin, bath, three." That is how a
printed phonemic chart teaches a sound too.

Recordings are made the first time the chart needs them, like Quick
Words pronunciations: the sound a learner opens is made there and then,
and the rest are filled in the background. An admin can regenerate any
recording, or upload a teacher's own, which is then left alone.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.core.files.base import ContentFile

from apps.quick_words.speech import SpeechUnavailable, is_configured, speak

from .models import ACADEMY, PhonemeAudio, Sound

logger = logging.getLogger(__name__)

EXAMPLE_WORDS = 3

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="phoneme-audio")
_filling = threading.Lock()


def chart_entries():
    """(key, symbol, keyword) for all 44 chart sounds, in chart order."""
    from .views import PHONEMIC_CHART  # the chart lives with its view

    return [entry for group in PHONEMIC_CHART for entry in group["sounds"]]


def _lesson_for(symbol):
    from .views import _normalize_symbol

    target = _normalize_symbol(symbol)
    for sound in Sound.objects.in_programme(ACADEMY).filter(is_published=True):
        if _normalize_symbol(sound.symbol) == target:
            return sound
    return None


def spoken_text(key, symbol):
    """What the recording says: the keyword, then a few example words."""
    text = f"{key}."
    lesson = _lesson_for(symbol)
    if lesson:
        examples = [w for w in lesson.example_word_list if w.lower() != key.lower()][:EXAMPLE_WORDS]
        if examples:
            text += " " + ", ".join(examples) + "."
    return text


def has_audio(row):
    return bool(row and (row.audio_file or row.audio_url))


def audio_by_key():
    """Every chart recording that exists, keyed by chart keyword."""
    return {row.key: row for row in PhonemeAudio.objects.all() if has_audio(row)}


def make_audio(key, symbol, replace=False):
    """Make (or remake) the recording for one chart sound.

    Returns the PhonemeAudio row, or None if ElevenLabs couldn't help.
    An uploaded recording is never replaced unless `replace` is asked for.
    """
    row, _ = PhonemeAudio.objects.get_or_create(key=key, defaults={"symbol": symbol})
    if has_audio(row) and not replace:
        return row
    if not is_configured():
        return None

    text = spoken_text(key, symbol)
    try:
        audio = speak(text)
    except SpeechUnavailable as error:
        logger.warning("No chart audio for %s: %s", key, error)
        return None

    old_file = row.audio_file.name if row.audio_file else ""
    row.symbol = symbol
    row.spoken_text = text
    row.source = PhonemeAudio.SOURCE_GENERATED
    row.audio_url = ""
    row.audio_file.save(f"phoneme-{key}.mp3", ContentFile(audio), save=False)
    row.save()
    if old_file and old_file != row.audio_file.name:
        row.audio_file.storage.delete(old_file)
    return row


def missing_entries():
    existing = audio_by_key()
    return [(key, symbol) for key, symbol, _name in chart_entries() if key not in existing]


def fill_missing():
    """Make every missing chart recording. Returns how many were made."""
    made = 0
    for key, symbol in missing_entries():
        if make_audio(key, symbol):
            made += 1
    return made


def fill_missing_in_background():
    """Start filling the gaps without holding up the page. Only one fill
    runs at a time, however many people open the chart."""
    if not is_configured() or not missing_entries():
        return False
    if not _filling.acquire(blocking=False):
        return False

    def run():
        try:
            fill_missing()
        finally:
            _filling.release()

    _pool.submit(run)
    return True
