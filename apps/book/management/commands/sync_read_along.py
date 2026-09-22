"""
Measure when each word is spoken, for every read-along recording.

    python manage.py sync_read_along            # only new or changed recordings
    python manage.py sync_read_along --all      # measure everything again

Pages do this by themselves the first time they're opened; this is for
filling everything in at once, e.g. after a big upload.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

from apps.book import read_along
from apps.book.models import ReadAlongTiming


class Command(BaseCommand):
    help = "Measure word timings for the read-along highlight."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Measure recordings that already have timings too.")
        parser.add_argument(
            "--rescore", action="store_true",
            help="Only work out again how well each recording matches its text, using what was already heard.",
        )

    def handle(self, *args, **options):
        if options["rescore"]:
            changed = 0
            for row in ReadAlongTiming.objects.select_related("content_type"):
                obj = row.content_object
                if obj is None or not row.words:
                    continue
                before = row.quality
                row.quality = read_along._spoken_share(read_along.text_for(obj), row.words)
                if row.quality != before:
                    row.save(update_fields=["quality", "updated_at"])
                    changed += 1
                self.stdout.write(f"  {str(obj)[:44]:46} {before if before is not None else '—'} → {row.quality:.0%}")
            self.stdout.write(self.style.SUCCESS(f"Rescored {changed} recording(s). Nothing was transcribed again."))
            return

        if not read_along.is_configured():
            raise CommandError("Needs ffmpeg plus ELEVENLABS_API_KEY or OPENAI_API_KEY.")

        done = skipped = failed = 0
        for obj in read_along.candidates():
            label = f"{obj._meta.verbose_name} {obj.pk} ({str(obj)[:50]})"
            if not options["all"]:
                status, _row = read_along.timing_for(obj, start=False)
                if status == "ready":
                    skipped += 1
                    continue
            row = read_along.measure(obj)
            if row and row.status == ReadAlongTiming.STATUS_READY:
                done += 1
                self.stdout.write(f"  ✓ {label}: {len(row.words)} words, {len(row.speech)} speech runs, {row.quality_label} via {row.engine or 'silence'}")
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  ✗ {label}: {row.error if row else 'nothing to measure'}"))

        # Timings whose passage, lesson or chapter has since been deleted.
        removed = 0
        for row in ReadAlongTiming.objects.select_related("content_type"):
            model = row.content_type.model_class()
            if model is None or not model.objects.filter(pk=row.object_id).exists():
                row.delete()
                removed += 1

        self.stdout.write(self.style.SUCCESS(
            f"Measured {done}, already done {skipped}, failed {failed}, tidied {removed}."
        ))
