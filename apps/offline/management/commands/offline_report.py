"""
python manage.py offline_report

How much a learner's app keeps at each level: pages by programme, and the
size of the stored pictures, audio and videos behind them, read from the
file storage. Reads only; changes nothing.
"""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.echospell.models import LEVEL_NAME_CHOICES
from apps.learning_tools.views import tools_for
from apps.offline.catalog import build


def stored_sizes():
    """{file name: bytes} for everything in storage, or {} if it can't be listed."""
    bucket = getattr(default_storage, "bucket", None)
    if bucket is None:
        return {}
    prefix = (getattr(default_storage, "location", "") or "").strip("/")
    cut = len(prefix) + 1 if prefix else 0
    objects = bucket.objects.filter(Prefix=prefix) if prefix else bucket.objects.all()
    return {item.key[cut:]: item.size for item in objects}


def megabytes(names, sizes):
    return sum(sizes.get(name, 0) for name in names) / 1048576


class Command(BaseCommand):
    help = "Report how big each level's offline download is (reads only)."

    def handle(self, *args, **options):
        sizes = stored_sizes()
        if not sizes:
            self.stdout.write("Storage can't be listed here, so sizes show as 0: page counts only.")
        for name, _label in LEVEL_NAME_CHOICES:
            pupil = User(role="student", level=name)
            shelf = build([name], {tool["url_name"] for tool in tools_for(pupil)})
            found = [item for item in shelf.files if item in sizes]
            self.stdout.write(
                f"{name}: {len(shelf.pages)} pages | {len(shelf.files)} pictures and audio, "
                f"{megabytes(shelf.files, sizes):.0f} MB ({len(found)} measured) | "
                f"{len(shelf.videos)} videos, {megabytes(shelf.videos, sizes):.0f} MB"
            )
            self.stdout.write("    " + ", ".join(f"{source} {count}" for source, count in shelf.counts.items()))
