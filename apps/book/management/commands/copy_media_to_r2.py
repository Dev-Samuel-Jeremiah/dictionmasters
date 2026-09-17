"""
Copy every uploaded file the database points at from this server's
media folder up to Cloudflare R2, keeping the same path, so switching
file storage to R2 doesn't break a single existing link.

Safe to run repeatedly: a file already on R2 is skipped, and nothing is
ever deleted — neither locally nor on R2. Once everything reports as on
R2 and the site has been checked, the local media folder can be removed
by hand.

    python manage.py copy_media_to_r2 --dry-run
    python manage.py copy_media_to_r2
"""

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import FileField
from storages.backends.s3 import S3Storage


def referenced_files():
    """{stored file name: ["app.Model #pk field", ...]} across every model."""
    refs = {}
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        fields = [f for f in model._meta.concrete_fields if isinstance(f, FileField)]
        for field in fields:
            rows = (
                model._default_manager.exclude(**{f"{field.name}__isnull": True})
                .exclude(**{field.name: ""})
                .values_list("pk", field.name)
            )
            for pk, name in rows:
                refs.setdefault(name, []).append(f"{model._meta.label} #{pk} {field.name}")
    return refs


class Command(BaseCommand):
    help = "Copy every uploaded file the database refers to from local media to Cloudflare R2."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would be copied without uploading.")

    def handle(self, *args, dry_run=False, **options):
        if not settings.R2_CONFIGURED:
            raise CommandError("R2 isn't configured — set the four R2_* values in .env first.")

        local = FileSystemStorage(location=settings.MEDIA_ROOT)
        r2 = S3Storage(**settings.R2_STORAGE_OPTIONS)
        refs = referenced_files()
        self.stdout.write(f"{len(refs)} file(s) referenced by the database.\n")

        copied, already, missing = [], [], []
        for name in sorted(refs):
            if r2.exists(name):
                already.append(name)
                continue
            if not local.exists(name):
                missing.append(name)
                continue

            size = local.size(name)
            if dry_run:
                self.stdout.write(f"  would copy  {name}  ({size / 1_048_576:.1f} MB)")
                copied.append(name)
                continue

            self.stdout.write(f"  copying     {name}  ({size / 1_048_576:.1f} MB) ...", ending="")
            self.stdout.flush()
            with local.open(name, "rb") as handle:
                saved_as = r2.save(name, File(handle, name=name))
            if saved_as != name:
                raise CommandError(f"R2 stored {name!r} as {saved_as!r}; stopping so links stay correct.")
            if not r2.exists(name) or r2.size(name) != size:
                raise CommandError(f"{name!r} didn't arrive intact on R2; stopping.")
            self.stdout.write(self.style.SUCCESS(" done"))
            copied.append(name)

        verb = "Would copy" if dry_run else "Copied"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{verb}: {len(copied)}"))
        self.stdout.write(f"Already on R2: {len(already)}")
        if missing:
            self.stdout.write(self.style.WARNING(
                f"Missing on this server too (these links were already broken): {len(missing)}"
            ))
            for name in missing:
                self.stdout.write(f"  {name}  <- {', '.join(refs[name])}")
