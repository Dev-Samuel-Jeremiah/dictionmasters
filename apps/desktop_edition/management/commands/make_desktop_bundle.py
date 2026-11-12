"""
python manage.py make_desktop_bundle --level "Level 1"

Packs one level's zip for flash drives (apps/desktop_edition/bundles.py):
its installers from GitHub and its videos from storage. /admin/ -> Offline
app downloads -> Add does the same in the background (--bundle).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.desktop_edition.bundles import build
from apps.desktop_edition.models import DesktopBundle


class Command(BaseCommand):
    help = "Pack one level's offline app zip (installers and videos) into storage."

    def add_arguments(self, parser):
        parser.add_argument("--level", default="", help='e.g. "Level 1"')
        parser.add_argument("--bundle", type=int, help="Pack this queued one (from /admin/).")

    def handle(self, *args, **options):
        if options["bundle"]:
            bundle = DesktopBundle.objects.filter(pk=options["bundle"]).first()
            if bundle is None:
                raise CommandError("No such bundle.")
        elif options["level"]:
            bundle = DesktopBundle.objects.create(level=options["level"])
        else:
            raise CommandError('Say which level: --level "Level 1".')
        bundle = build(bundle, log=lambda text: self.stdout.write(text))
        if bundle.status != DesktopBundle.Status.READY:
            raise CommandError(bundle.error)
        self.stdout.write(self.style.SUCCESS(f"{bundle.file}: {bundle.size / 1073741824:.1f} GB, {bundle.videos} videos."))
