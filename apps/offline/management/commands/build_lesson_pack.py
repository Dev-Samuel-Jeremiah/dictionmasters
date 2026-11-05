"""
python manage.py build_lesson_pack <pack id>

Builds one lesson pack (apps/offline/packs.py). Started by the control room
in its own process, so a long build survives the web server restarting.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.offline.models import LessonPack
from apps.offline.packs import build

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Build one lesson pack."

    def add_arguments(self, parser):
        parser.add_argument("pack", type=int)

    def handle(self, *args, **options):
        pack = LessonPack.objects.get(pk=options["pack"])
        try:
            build(pack)
        except Exception as error:                       # recorded for the control room, then raised
            logger.exception("Lesson pack %s failed", pack.pk)
            LessonPack.objects.filter(pk=pack.pk).update(status=LessonPack.Status.FAILED, error=str(error)[:2000],
                                                         finished_at=timezone.now())
            raise
        self.stdout.write(f"{pack.level}: {pack.files_done} files, {pack.videos} videos, {pack.size / 1048576:.0f} MB")
