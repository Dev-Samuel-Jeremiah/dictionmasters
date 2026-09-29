"""
Read Diction Library books aloud (see apps/diction_library/narration.py).

    python manage.py narrate_library              # everything new, changed or unfinished
    python manage.py narrate_library --dry-run    # just list it, with the characters it would use
    python manage.py narrate_library --item the-magic-talking-drum [--force]

Books are read aloud by themselves when saved; this is for finishing one
that was interrupted, or for a whole library at once. Chapters already made
from the same words are kept, so it can be stopped and run again.
"""

from django.core.management.base import BaseCommand

from apps.diction_library import narration
from apps.diction_library.models import LibraryItem


class Command(BaseCommand):
    help = "Make the read-aloud audio (with word highlighting) for Diction Library books."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Make nothing: list what would be made and its size.")
        parser.add_argument("--item", help="Only this item (its slug).")
        parser.add_argument("--force", action="store_true", help="Make it again even if it's up to date.")

    def handle(self, *args, **options):
        items = LibraryItem.objects.all()
        if options["item"]:
            items = items.filter(slug=options["item"])
        due = [item for item in items if options["force"] or narration.needs_narration(item)]
        due = [item for item in due if narration.wants_reading(item)]
        if not due:
            self.stdout.write(self.style.SUCCESS("Every book's read-aloud is up to date."))
            return
        total = 0
        for item in due:
            if options["dry_run"]:
                try:
                    chapters = narration.main_chapters(narration.book_paragraphs(item), item.title)
                except narration.NarrationUnavailable as error:
                    self.stdout.write(self.style.WARNING(f"  ✗ {item.title}: {error}"))
                    continue
                chars = sum(len("\n\n".join(p)) for _t, p in chapters)
                total += 0 if item.narration_file else chars
                how = "uses its uploaded recording" if item.narration_file else f"{chars:,} characters to read"
                self.stdout.write(f"  {item.title[:50]:52} {len(chapters):3} chapter(s), {how}")
                continue
            self.stdout.write(f"  … {item.title}")
            narration.narrate(item, force=options["force"])
            item.refresh_from_db()
            style = self.style.SUCCESS if item.narration_status == "ready" else self.style.WARNING
            self.stdout.write(style(f"    {item.narration_status}: {item.narration_note}"))
        if options["dry_run"]:
            self.stdout.write(f"Would read {total:,} characters with the ElevenLabs voice. Nothing was made.")
