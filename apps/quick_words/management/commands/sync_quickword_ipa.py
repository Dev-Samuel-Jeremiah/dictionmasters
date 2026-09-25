"""Backward-compatible alias for the Britfone-first IPA synchronization."""

from .import_british_ipa import Command as ImportBritishIPACommand


class Command(ImportBritishIPACommand):
    help = "Refresh Quick Words IPA from the local Britfone and IPA-Dict datasets."
