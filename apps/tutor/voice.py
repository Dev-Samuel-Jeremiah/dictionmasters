"""Tutor narration and pronunciation, using the project-wide ElevenLabs voice.

Cached recordings are keyed by that voice ID; different tutor avatars retain
separate faces and names but share one pronunciation voice.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, close_old_connections

from apps.quick_words.speech import SpeechUnavailable, is_configured, speak, synthesise

from .models import TutorChoice, TutorSpeech, TutorVoice

logger = logging.getLogger(__name__)

_keeper = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tutor-voice")


def bare(word):
    return re.sub(r"^[^\w]+|[^\w]+$", "", str(word or ""))


def _tidy(text, single_word):
    text = " ".join(str(text or "").split())
    return bare(text) if single_word else text


def _url(field):
    try:
        return field.url
    except ValueError:
        return ""


def for_user(user):
    """The voice this learner has chosen, or the site's usual one."""
    return TutorChoice.voice_for(user)


def _voice_id():
    """All tutor avatars use the single project ElevenLabs voice."""
    return getattr(settings, "ELEVENLABS_VOICE_ID", "")


def kept_url(text, single_word=False):
    """Where a recording of `text` in this voice already lives, or ""."""
    text = _tidy(text, single_word)
    if not text:
        return ""
    kept = TutorSpeech.objects.filter(key=TutorSpeech.key_for(text, _voice_id())).first()
    return _url(kept.audio) if kept else ""


def make(text, single_word=False):
    """Fresh MP3 bytes of `text` spoken, or None if the voice is unavailable."""
    text = _tidy(text, single_word)
    if not text or not is_configured():
        return None
    model = getattr(settings, "TUTOR_VOICE_MODEL_ID", None)
    try:
        return (synthesise(text, model_id=model) if single_word
                else speak(text, model_id=model))
    except SpeechUnavailable as error:
        logger.warning("Tutor voice unavailable: %s", error)
        return None


def _keep(text, audio, voice_id=""):
    try:
        key = TutorSpeech.key_for(text, voice_id)
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
    _keeper.submit(_keep, _tidy(text, single_word), audio, _voice_id())
