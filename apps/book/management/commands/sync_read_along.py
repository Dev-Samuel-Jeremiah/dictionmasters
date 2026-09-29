"""
Measure when each word is spoken, for every read-along recording.

    python manage.py sync_read_along            # only new or changed recordings
    python manage.py sync_read_along --dry-run  # just say what that would measure, and the rough cost
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
            "--dry-run", action="store_true",
            help="Measure nothing: list what would be measured, and roughly what it would cost.",
        )
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
        planned, minutes, unknown = {}, 0.0, 0
        for obj in read_along.candidates():
            label = f"{obj._meta.verbose_name} {obj.pk} ({str(obj)[:50]})"
            if not options["all"]:
                status, existing = read_along.timing_for(obj, start=False)
                # Only the voice's pauses because the word service failed last
                # time: try the words again.
                if status == "ready" and not read_along.needs_retry(existing):
                    skipped += 1
                    continue
            if options["dry_run"]:
                kind = str(obj._meta.verbose_name)
                planned[kind] = planned.get(kind, 0) + 1
                known = ReadAlongTiming.objects.filter(
                    content_type=read_along._content_type(obj), object_id=obj.pk).values_list("duration", flat=True).first()
                if known:
                    minutes += known / 60
                else:
                    unknown += 1
                continue
            row = read_along.measure(obj)
            if row and row.status == ReadAlongTiming.STATUS_READY and read_along.needs_retry(row):
                # Usable (the highlight follows the voice), but the words
                # didn't come back: say why, so it can be put right.
                failed += 1
                self.stdout.write(self.style.WARNING(
                    f"  ~ {label}: no words — following the voice only. Why: {row.error}"
                ))
            elif row and row.status == ReadAlongTiming.STATUS_READY:
                done += 1
                self.stdout.write(f"  ✓ {label}: {len(row.words)} words, {len(row.speech)} speech runs, {row.quality_label} via {row.engine or 'silence'}")
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  ✗ {label}: {row.error if row else 'nothing to measure'}"))

        if options["dry_run"]:
            total = sum(planned.values())
            self.stdout.write(f"Would measure {total} recording(s); {skipped} already up to date would be skipped.")
            for kind, count in sorted(planned.items(), key=lambda row: -row[1]):
                self.stdout.write(f"  {count:5}  {kind}")
            if total:
                # OpenAI Whisper: about $0.006 a minute, and each recording is
                # listened to twice (with and without the text as a hint).
                cost = minutes * 0.006 * 2
                self.stdout.write(
                    f"Known length: {minutes:.0f} minutes of audio ≈ ${cost:.2f} with OpenAI"
                    + (f", plus {unknown} recording(s) not measured before (length unknown)." if unknown else ".")
                )
            self.stdout.write("Nothing was measured. Run without --dry-run to do it.")
            return

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
