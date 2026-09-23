"""Refresh cached tutor speech entries that were made with another voice ID."""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.quick_words.speech import SpeechUnavailable, is_configured, speak
from apps.tutor.models import TutorSpeech


class Command(BaseCommand):
    help = "Refresh cached tutor speech to use the configured project-wide ElevenLabs voice."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List stale cache entries without changing them.")

    def handle(self, *args, **options):
        if not is_configured():
            raise CommandError("ElevenLabs is not configured (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID).")
        voice_id = settings.ELEVENLABS_VOICE_ID
        rows = [row for row in TutorSpeech.objects.all().order_by("created_at")
                if row.key != TutorSpeech.key_for(row.text, voice_id)]
        if options["dry_run"]:
            self.stdout.write(f"Would refresh {len(rows)} tutor cache entries.")
            return

        made = failed = skipped = 0
        model_id = getattr(settings, "TUTOR_VOICE_MODEL_ID", None)
        for old in rows:
            new_key = TutorSpeech.key_for(old.text, voice_id)
            current = TutorSpeech.objects.filter(key=new_key).first()
            if current:
                old.audio.storage.delete(old.audio.name)
                old.delete()
                skipped += 1
                continue
            try:
                audio = speak(old.text, model_id=model_id)
                new = TutorSpeech(key=new_key, text=old.text)
                new.audio.save(f"{new_key[:16]}.mp3", ContentFile(audio), save=False)
                new.save()
                old.audio.storage.delete(old.audio.name)
                old.delete()
                made += 1
                self.stdout.write(f"Updated cached tutor speech: {old.text[:70]}")
            except SpeechUnavailable as error:
                failed += 1
                self.stderr.write(self.style.WARNING(f"Could not regenerate {old.text[:70]}: {error}"))

        self.stdout.write(self.style.SUCCESS(f"Regenerated {made}; removed duplicate stale entries {skipped}; failed {failed}."))
