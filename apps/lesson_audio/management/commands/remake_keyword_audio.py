"""Make every lesson note key word's audio again with the current word
voice (apps/lesson_audio/services.py: _word_audio).

    python manage.py remake_keyword_audio             # every key word
    python manage.py remake_keyword_audio --note 12   # one lesson note
    python manage.py remake_keyword_audio --dry-run   # just count them

Safe to stop and run again: a word is only changed once its new audio is
ready. A copied note shares its recordings with the original, so each
distinct word is made once and given to every key word that says it.
"""

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.lesson_audio import services
from apps.lesson_audio.models import KeyWord


class Command(BaseCommand):
    help = "Make lesson-note key word audio again with the current ElevenLabs voice and model."

    def add_arguments(self, parser):
        parser.add_argument("--note", type=int, help="Only this lesson note.")
        parser.add_argument("--dry-run", action="store_true", help="Count the words without making anything.")

    def handle(self, *args, **options):
        words = KeyWord.objects.all().order_by("word")
        if options["note"]:
            words = words.filter(note_id=options["note"])
        groups = {}
        for word in words:
            groups.setdefault(word.word.lower(), []).append(word)
        self.stdout.write(f"{len(groups)} distinct key word(s) in {words.count()} place(s).")
        if options["dry_run"]:
            return
        made = failed = 0
        for n, (term, same) in enumerate(groups.items(), start=1):
            audio = services._word_audio(same[0].word)
            if not audio:
                failed += 1
                self.stdout.write(self.style.WARNING(f"[{n}/{len(groups)}] {same[0].word}: no audio, kept the old one"))
                continue
            old = {w.audio_file.name for w in same if w.audio_file}
            first = same[0]
            first.audio_file.save(f"{slugify(first.word) or 'word'}.mp3", ContentFile(audio), save=True)
            for other in same[1:]:
                other.audio_file.name = first.audio_file.name
                other.save(update_fields=["audio_file"])
            for name in old - {first.audio_file.name}:
                services.forget_file(name, first.audio_file.storage)
            made += 1
            self.stdout.write(f"[{n}/{len(groups)}] {first.word}: done")
        self.stdout.write(self.style.SUCCESS(f"Made {made} word recording(s); {failed} could not be made."))
