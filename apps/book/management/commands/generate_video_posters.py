"""
Make the thumbnail for every uploaded video that hasn't got one.

    python manage.py generate_video_posters
    python manage.py generate_video_posters --replace   # remake them all

A poster uploaded by an admin is replaced only with --replace.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.book import video_poster


class Command(BaseCommand):
    help = "Take a thumbnail from each video with ffmpeg."

    def add_arguments(self, parser):
        parser.add_argument("--replace", action="store_true", help="Remake posters that already exist.")

    def handle(self, *args, **options):
        if not video_poster.thumbnails_available():
            raise CommandError("ffmpeg isn't installed, so thumbnails can't be made.")

        made = failed = 0
        for model in video_poster.video_models():
            rows = model.objects.exclude(video_file="", video_url="")
            if not options["replace"]:
                rows = rows.filter(video_poster="")
            for instance in rows:
                if video_poster.make_poster(instance, replace=options["replace"]):
                    made += 1
                    self.stdout.write(f"  {model.__name__} {instance.pk}: {instance.video_poster.name}")
                else:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"  {model.__name__} {instance.pk}: no frame taken"))

        self.stdout.write(self.style.SUCCESS(f"Made {made}, skipped or failed {failed}."))
