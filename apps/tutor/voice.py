"""
The tutor's voice: how a word or sentence should sound.

  1. A word already in Quick Words with its own recording is played from
     there — the same pronunciation the learner meets everywhere else.
  2. A word or sentence the tutor has said before is played from where it
     was kept (TutorSpeech), so it's only ever paid for once.
  3. Otherwise it's spoken by the site's ElevenLabs voice, using the fast
     model, and played straight away; it's kept in the background, since
     saving to storage takes longer than making it.
  4. If none of that works, the page uses the browser's own voice rather
     than leave the learner without a model.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, close_old_connections

from apps.quick_words.models import QuickWord
from apps.quick_words.speech import SpeechUnavailable, is_configured, speak, synthesise

from .models import TutorSpeech

logger = logging.getLogger(__name__)

_keeper = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tutor-voice")


def bare(word):
    return re.sub(r"^[^\w]+|[^\w]+$", "", str(word or ""))


def library_word(word):
    """The Quick Words entry for `word`, if there is one."""
    word = bare(word)
    if not word:
        return None
    return QuickWord.objects.filter(is_published=True, word__iexact=word).first()


def _tidy(text, single_word):
    text = " ".join(str(text or "").split())
    return bare(text) if single_word else text


def _url(field):
    try:
        return field.url
    except ValueError:
        return ""


def kept_url(text, single_word=False):
    """Where a recording of `text` already lives, or ""."""
    text = _tidy(text, single_word)
    if not text:
        return ""
    if single_word:
        entry = library_word(text)
        if entry and entry.audio_source:
            return entry.audio_source
    kept = TutorSpeech.objects.filter(key=TutorSpeech.key_for(text)).first()
    return _url(kept.audio) if kept else ""


def make(text, single_word=False):
    """Fresh MP3 bytes of `text` spoken, or None if the voice is unavailable."""
    text = _tidy(text, single_word)
    if not text or not is_configured():
        return None
    model = getattr(settings, "TUTOR_VOICE_MODEL_ID", None)
    try:
        return synthesise(text, model_id=model) if single_word else speak(text, model_id=model)
    except SpeechUnavailable as error:
        logger.warning("Tutor voice unavailable: %s", error)
        return None


def _keep(text, audio):
    try:
        key = TutorSpeech.key_for(text)
        if TutorSpeech.objects.filter(key=key).exists():
            return
        kept = TutorSpeech(key=key, text=text[:600])
        kept.audio.save(f"{key[:16]}.mp3", ContentFile(audio), save=False)
        kept.save()
    except IntegrityError:
        pass   # kept at the same moment by another request
    except Exception:   # storage trouble must never reach the learner
        logger.exception("Couldn't keep the tutor's recording of %r.", text[:60])
    finally:
        close_old_connections()


def keep_later(text, audio, single_word=False):
    _keeper.submit(_keep, _tidy(text, single_word), audio)
