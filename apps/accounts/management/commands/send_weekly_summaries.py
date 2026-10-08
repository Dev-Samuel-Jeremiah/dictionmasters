"""The Monday emails: each learner's week for their grown-ups, and each
teacher's "Needs help" list (apps/accounts/weekly.py). Run weekly by a
systemd timer; see docs/deploy.md. Safe to run again: anyone already
sent this week's is skipped."""

from django.core.management.base import BaseCommand

from apps.accounts.weekly import send_weekly


class Command(BaseCommand):
    help = "Send the weekly learner summaries and the teachers' 'Needs help' emails."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List who would get an email; send nothing.")

    def handle(self, *args, dry_run=False, **options):
        sent = send_weekly(dry_run=dry_run, out=self.stdout.write if dry_run else None)
        verb = "Would send" if dry_run else "Sent"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {sent['learners']} weekly summar{'y' if sent['learners'] == 1 else 'ies'} "
            f"and {sent['teachers']} 'Needs help' email{'' if sent['teachers'] == 1 else 's'}."
        ))
