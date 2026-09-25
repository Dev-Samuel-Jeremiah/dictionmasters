"""Sync trusted local British IPA into existing QuickWord cards."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.quick_words import british_ipa, ipa_dict as ipa_dict_module
from apps.quick_words.british_ipa import get_british_ipa, load_britfone
from apps.quick_words.ipa_dict import load_ipa_dict
from apps.quick_words.models import QuickWord


class Command(BaseCommand):
    help = "Import Britfone and IPA-Dict UK pronunciations into existing Quick Words."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report updates without saving them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        britfone = load_britfone()
        ipa_entries = load_ipa_dict()
        invalid_entries = (
            british_ipa.BRITFONE_INVALID_ENTRIES + ipa_dict_module.IPA_DICT_INVALID_ENTRIES
        )

        counts = {"britfone": 0, "ipa_dict": 0}
        unchanged = 0
        scanned = 0
        for word in QuickWord.objects.order_by("word").iterator():
            scanned += 1
            pronunciation = get_british_ipa(word.word, allow_ai=False)
            if pronunciation["source"] not in counts or not pronunciation["ipa"]:
                continue

            fields = {
                "ipa": pronunciation["ipa"],
                "ipa_accent": pronunciation["accent"],
                "ipa_source": pronunciation["source"],
                "ipa_confidence": pronunciation["confidence"],
                "ipa_review_required": pronunciation["review_required"],
            }
            if all(getattr(word, name) == value for name, value in fields.items()):
                unchanged += 1
                continue

            self.stdout.write(
                f"{word.word}: {word.ipa or '(blank)'} -> {fields['ipa']} "
                f"[{fields['ipa_source']}]"
            )
            if not dry_run:
                for name, value in fields.items():
                    setattr(word, name, value)
                word.save(update_fields=[*fields, "updated_at"])
            counts[pronunciation["source"]] += 1

        action = "Would import" if dry_run else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{action}: Britfone {counts['britfone']}; IPA-Dict {counts['ipa_dict']}; "
            f"duplicates skipped {unchanged}; invalid entries {invalid_entries}; "
            f"total Quick Words scanned {scanned}."
        ))
        self.stdout.write(
            f"Local datasets loaded: Britfone {len(britfone)} words; "
            f"IPA-Dict UK {len(ipa_entries)} words."
        )
