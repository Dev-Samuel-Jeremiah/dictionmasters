"""Check that the voice the tutor teaches with is a British one.

    python manage.py tutor_voice

Everything the tutor models has to be British English, so this asks
ElevenLabs what the configured voice actually is and says plainly whether
it fits. Run it after changing ELEVENLABS_VOICE_ID.
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.book.read_along import _http

VOICE_URL = "https://api.elevenlabs.io/v1/voices/{voice_id}"


class Command(BaseCommand):
    help = "Show the tutor's voice and whether it is British."

    def handle(self, *args, **options):
        voice_id = getattr(settings, "ELEVENLABS_VOICE_ID", "")
        if not (settings.ELEVENLABS_API_KEY and voice_id):
            self.stdout.write(self.style.WARNING(
                "No ElevenLabs voice is set, so the tutor falls back to the browser's own "
                "British voice. Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID."))
            return

        try:
            answer = _http.request(
                "GET", VOICE_URL.format(voice_id=voice_id),
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY}, timeout=20,
            )
            voice = json.loads(answer.data.decode("utf-8"))
        except Exception as error:
            raise SystemExit(f"Couldn't ask ElevenLabs about the voice: {error}")

        labels = voice.get("labels") or {}
        accent = str(labels.get("accent", "")).lower()
        name = voice.get("name", voice_id)
        self.stdout.write(f"Voice: {name}")
        self.stdout.write(f"  accent: {accent or 'not stated'}")
        for key in ("description", "age", "gender", "use_case"):
            if labels.get(key):
                self.stdout.write(f"  {key}: {labels[key]}")
        self.stdout.write(f"  model for the tutor: {getattr(settings, 'TUTOR_VOICE_MODEL_ID', '')}")

        if any(word in accent for word in ("british", "english", "uk", "received")):
            self.stdout.write(self.style.SUCCESS("This is a British voice — the tutor is teaching British English."))
        elif accent:
            self.stdout.write(self.style.ERROR(
                f"This voice is {accent}, not British. Every word the tutor models would teach that accent. "
                "Choose a British voice in ElevenLabs and set ELEVENLABS_VOICE_ID to it."))
        else:
            self.stdout.write(self.style.WARNING(
                "ElevenLabs doesn't say what accent this voice has. Listen to a word in Quick Words "
                "and make sure it sounds British."))
