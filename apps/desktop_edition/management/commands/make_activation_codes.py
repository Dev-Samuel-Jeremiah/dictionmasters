"""
python manage.py make_activation_codes --holder "White Diamonds Academy" --count 30 \
    [--levels "Level 1,Level 2"] [--seats 1] [--until 2027-07-31]

Makes activation codes for the offline computer app and prints them, one per
line, ready to paste into a spreadsheet or print. (Or make them in /admin/.)
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.desktop_edition.models import ActivationCode
from apps.echospell.models import LEVEL_NAME_CHOICES


class Command(BaseCommand):
    help = "Make activation codes for the offline computer app."

    def add_arguments(self, parser):
        parser.add_argument("--holder", required=True)
        parser.add_argument("--count", type=int, default=1)
        parser.add_argument("--levels", default="", help="Empty for every level.")
        parser.add_argument("--seats", type=int, default=1, help="Computers per code.")
        parser.add_argument("--until", default="", help="YYYY-MM-DD; empty for no end.")

    def handle(self, *args, **options):
        known = {value for value, _label in LEVEL_NAME_CHOICES}
        levels = [part.strip() for part in options["levels"].split(",") if part.strip()]
        unknown = [level for level in levels if level not in known]
        if unknown:
            raise CommandError(f"Unknown level(s): {', '.join(unknown)}. Use e.g. \"Level 1\" or \"Pre-Level\".")
        until = date.fromisoformat(options["until"]) if options["until"] else None
        for _ in range(max(1, options["count"])):
            code = ActivationCode(holder=options["holder"], seats=max(1, options["seats"]), valid_until=until)
            code.set_levels(levels)
            code.save()
            self.stdout.write(code.code)
