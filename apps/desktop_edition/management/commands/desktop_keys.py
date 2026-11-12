"""
python manage.py desktop_keys

Prints two new secret lines for the server's .env, for the offline computer
app (apps/desktop_edition/keys.py). Do this ONCE, before the first real
installer, then never change them: installed apps can only open lessons
sealed with DESKTOP_CONTENT_KEY, and only trust licences signed with
DESKTOP_LICENCE_PRIVATE_KEY. Keep a copy somewhere safe.

The app learns the matching public key from /desktop-app/public-key/ when
it's built, so there's nothing to copy into the app.
"""

from django.core.management.base import BaseCommand

from apps.desktop_edition.keys import new_keys, public_key_b64


class Command(BaseCommand):
    help = "Print new keys for the offline computer app (.env lines)."

    def add_arguments(self, parser):
        parser.add_argument("--show-public", action="store_true", help="Just print the public key in use now.")

    def handle(self, *args, **options):
        if options["show_public"]:
            self.stdout.write(public_key_b64())
            return
        for name, value in new_keys().items():
            self.stdout.write(f"{name}={value}")
        self.stdout.write(self.style.WARNING("Add these to .env, restart, and never change them afterwards."))
