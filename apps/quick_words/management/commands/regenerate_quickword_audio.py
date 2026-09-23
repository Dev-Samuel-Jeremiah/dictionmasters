"""Regenerate AI-created Quick Words clips with the configured ElevenLabs voice."""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.quick_words.models import QuickWord
from apps.quick_words.speech import SpeechUnavailable, is_configured, synthesise


class Command(BaseCommand):
    help = "Regenerate saved AI-created Quick Words audio with the configured ElevenLabs voice."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List clips without changing them.")

    def handle(self, *args, **options):
        if not is_configured():
            raise CommandError("ElevenLabs is not configured (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID).")
        rows = list(QuickWord.objects.filter(source=QuickWord.SOURCE_AI).exclude(audio_file="").filter(audio_url="").order_by("word"))
        if options["dry_run"]:
            self.stdout.write(f"Would regenerate {len(rows)} AI-created Quick Words clips.")
            return

        made = failed = 0
        for word in rows:
            old_name = word.audio_file.name
            try:
                audio = synthesise(word.word)
                word.audio_file.save(f"{word.slug}.mp3", ContentFile(audio), save=False)
                word.save(update_fields=["audio_file"])
                if old_name and old_name != word.audio_file.name:
                    word.audio_file.storage.delete(old_name)
                made += 1
                self.stdout.write(f"Updated {word.word}")
            except SpeechUnavailable as error:
                failed += 1
                self.stderr.write(self.style.WARNING(f"Could not regenerate {word.word}: {error}"))

        self.stdout.write(self.style.SUCCESS(f"Regenerated {made}; failed {failed}."))
