"""
python manage.py export_desktop_content [--levels "Level 1,Level 2"] [--no-videos] [--to FOLDER]
python manage.py export_desktop_content --release <id>       (started from /admin/)

Builds a new release of every lesson for the offline computer app
(apps/desktop_edition/export.py). Installed apps download what changed the
next time they're online. --to also writes the release to a folder, as the
installer carries it (manifest.json and blobs/), e.g. to try the app with
lessons from your own computer.
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.desktop_edition.export import build, read_manifest, write_folder
from apps.desktop_edition.models import ContentRelease

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Build a release of the lessons for the offline computer app."

    def add_arguments(self, parser):
        parser.add_argument("--release", type=int, help="Build this queued release (from /admin/).")
        parser.add_argument("--levels", default="", help='Only these levels, e.g. "Level 1,Level 2".')
        parser.add_argument("--no-videos", action="store_true", help="Leave videos out (they need the internet then).")
        parser.add_argument("--to", default="", help="Also write the release to this folder.")

    def handle(self, *args, **options):
        if options["release"]:
            release = ContentRelease.objects.filter(pk=options["release"]).first()
            if release is None:
                raise CommandError("No such release.")
        else:
            levels = ",".join(part.strip() for part in options["levels"].split(",") if part.strip())
            release = ContentRelease.objects.create(levels=levels, include_videos=not options["no_videos"])
        try:
            build(release, log=self.stdout.write)
        except Exception as error:
            logger.exception("Desktop release %s failed", release.pk)
            ContentRelease.objects.filter(pk=release.pk).update(
                status=ContentRelease.Status.FAILED, error=str(error)[:4000], finished_at=timezone.now())
            raise
        self.stdout.write(self.style.SUCCESS(
            f"Release {release.pk}: {release.pages} pages, {release.files} files, "
            f"{release.size / 1048576:.0f} MB ({release.new_size / 1048576:.0f} MB new)."))
        if release.skipped:
            self.stdout.write(f"{len(release.skipped.splitlines())} left out (see the release in /admin/).")
        if options["to"]:
            count = write_folder(read_manifest(release), options["to"])
            self.stdout.write(f"Written to {options['to']}: {count} files.")
