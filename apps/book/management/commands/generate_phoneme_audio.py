"""
Make the spoken recording for every phonemic chart sound.

    python manage.py generate_phoneme_audio            # only the missing ones
    python manage.py generate_phoneme_audio --replace  # remake generated ones too

Uploaded teacher recordings are never replaced.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.book import phoneme_audio
from apps.book.models import PhonemeAudio
from apps.quick_words.speech import is_configured


class Command(BaseCommand):
    help = "Generate ElevenLabs audio for the phonemic chart."

    def add_arguments(self, parser):
        parser.add_argument("--replace", action="store_true", help="Remake recordings that were generated before.")

    def handle(self, *args, **options):
        if not is_configured():
            raise CommandError("ElevenLabs isn't configured (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID).")

        existing = {row.key: row for row in PhonemeAudio.objects.all()}
        made = skipped = failed = 0
        for key, symbol, _name in phoneme_audio.chart_entries():
            row = existing.get(key)
            has = phoneme_audio.has_audio(row)
            uploaded = row is not None and row.source == PhonemeAudio.SOURCE_UPLOADED
            if has and (uploaded or not options["replace"]):
                skipped += 1
                continue
            result = phoneme_audio.make_audio(key, symbol, replace=True)
            if phoneme_audio.has_audio(result):
                made += 1
                self.stdout.write(f"  /{symbol}/ {key}: “{result.spoken_text}”")
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  /{symbol}/ {key}: failed"))

        self.stdout.write(self.style.SUCCESS(f"Made {made}, kept {skipped}, failed {failed}."))
