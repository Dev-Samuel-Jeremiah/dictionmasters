"""
Long-running console jobs, run in the background so the admin page
returns straight away: filling in pronunciation audio that is missing.

Only one job of each kind runs at a time. Existing audio is never
replaced; these only fill gaps.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.core.files.base import ContentFile
from django.db import close_old_connections

from apps.book import phoneme_audio, video_poster
from apps.quick_words.models import QuickWord
from apps.quick_words.speech import SpeechUnavailable, is_configured, synthesise

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="console-job")
_word_lock = threading.Lock()


def words_without_audio():
    return QuickWord.objects.filter(is_published=True, audio_file="", audio_url="")


def _fill_word_audio():
    close_old_connections()
    try:
        for word in words_without_audio().order_by("word"):
            try:
                audio = synthesise(word.word)
            except SpeechUnavailable as error:
                logger.warning("No pronunciation for %r: %s", word.word, error)
                continue
            word.audio_file.save(f"{word.slug}.mp3", ContentFile(audio), save=True)
    finally:
        close_old_connections()
        _word_lock.release()


def start_word_audio():
    """Start generating pronunciations for every word that has none.
    Returns False if ElevenLabs isn't set up, nothing is missing, or a
    run is already going."""
    if not is_configured() or not words_without_audio().exists():
        return False
    if not _word_lock.acquire(blocking=False):
        return False
    _pool.submit(_fill_word_audio)
    return True


def word_audio_running():
    return _word_lock.locked()


def start_chart_audio():
    return phoneme_audio.fill_missing_in_background()


def videos_without_posters():
    """How many uploaded videos are still showing a black first frame."""
    return sum(found.count() for _model, found in video_poster.missing_posters())


def start_video_posters():
    return video_poster.fill_missing_in_background()
