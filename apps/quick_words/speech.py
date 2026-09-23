"""
Spoken pronunciation for Quick Words, generated with ElevenLabs.

The word is spoken as a complete statement ("thorough.") rather than a
bare word. Read on its own, a word often comes out with a rising,
unfinished lift, as if the speaker were about to say more; the full
stop gives it the clear falling tone a teacher uses when saying it once.

A failure here is never fatal. A word without audio is still a useful
dictionary entry, so callers catch SpeechUnavailable and carry on.
"""

import json
import urllib.error
import urllib.request

from django.conf import settings

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
TIMEOUT_SECONDS = 20

# A spoken word is a second or two of audio. Anything far outside this
# is an error page or a runaway response, not a pronunciation.
MIN_AUDIO_BYTES = 2_000
MAX_AUDIO_BYTES = 4_000_000

# Steady and clear rather than expressive: the same word should sound
# the same every time a child plays it.
VOICE_SETTINGS = {"stability": 0.6, "similarity_boost": 0.8}


class SpeechUnavailable(Exception):
    """The audio couldn't be made — no key, network trouble, or a reply
    that wasn't audio."""


def _looks_like_mp3(data):
    return data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def is_configured():
    return bool(settings.ELEVENLABS_API_KEY and settings.ELEVENLABS_VOICE_ID)


def synthesise(word, model_id=None):
    """MP3 bytes of `word` being pronounced."""
    return speak(f"{str(word).strip()}.", model_id=model_id)


def speak(text, model_id=None):
    """MP3 bytes of `text` read aloud, exactly as written. Used directly
    where the wording matters, such as a phonemic chart keyword followed
    by its example words."""
    if not is_configured():
        raise SpeechUnavailable("ElevenLabs is not configured.")

    body = {
        "text": str(text).strip(),
        "model_id": model_id or settings.ELEVENLABS_MODEL_ID,
        "voice_settings": VOICE_SETTINGS,
    }
    request = urllib.request.Request(
        API_URL.format(voice_id=settings.ELEVENLABS_VOICE_ID),
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "xi-api-key": settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "dictionmasters/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            audio = response.read(MAX_AUDIO_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise SpeechUnavailable(f"ElevenLabs answered HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SpeechUnavailable("Couldn't reach ElevenLabs.") from error

    if not (MIN_AUDIO_BYTES <= len(audio) <= MAX_AUDIO_BYTES) or not _looks_like_mp3(audio):
        raise SpeechUnavailable("ElevenLabs didn't return usable audio.")
    return audio
