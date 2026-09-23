"""Refresh saved Quick Words transcriptions from the bundled en_UK IPA-Dict."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.quick_words.ipa_dict import get_ipa
from apps.quick_words.models import QuickWord


class Command(BaseCommand):
    help = "Update Quick Words IPA from the bundled en_UK dictionary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report the changes without saving them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        updated = 0
        unchanged = 0
        missing = []
        for word in QuickWord.objects.order_by("word"):
            ipa = get_ipa(word.word)
            if not ipa:
                missing.append(word.word)
                continue
            if ipa == word.ipa:
                unchanged += 1
                continue
            self.stdout.write(f"{word.word}: {word.ipa or '(blank)'} -> {ipa}")
            if not dry_run:
                word.ipa = ipa
                word.save(update_fields=["ipa"])
            updated += 1

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {updated}; {unchanged} already matched en_UK IPA-Dict."
        ))
        if missing:
            self.stdout.write(self.style.WARNING(
                "No en_UK IPA entry; left unchanged: " + ", ".join(missing)
            ))
