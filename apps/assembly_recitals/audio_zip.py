"""Attach audio files from a ZIP to Assembly Recitals."""

import logging
import re
import stat
import unicodedata
import zipfile
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import slugify

from .models import Recital, Section

logger = logging.getLogger(__name__)

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_AUDIO_FILES = 100
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".webm"}


class AudioZipError(ValueError):
    """The archive is invalid, too large, or has no supported audio files."""


def _audio_entries(archive):
    entries = []
    total_size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise AudioZipError("The ZIP contains an unsafe file path.")
        suffix = path.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            continue
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            continue
        if info.flag_bits & 0x1:
            raise AudioZipError(f"{path.name} is password protected. Please upload an unprotected ZIP.")
        if info.file_size > MAX_AUDIO_BYTES:
            raise AudioZipError(f"{path.name} is larger than the 50 MB per-audio limit.")
        total_size += info.file_size
        if total_size > MAX_UNPACKED_BYTES:
            raise AudioZipError("The ZIP expands beyond the 600 MB total audio limit.")
        entries.append((info, path, suffix))
        if len(entries) > MAX_AUDIO_FILES:
            raise AudioZipError(f"The ZIP contains more than {MAX_AUDIO_FILES} audio files.")
    if not entries:
        raise AudioZipError("The ZIP has no supported audio files.")
    return entries


def inspect_audio_zip(upload):
    """Validate an archive without extracting it and return its audio count."""
    if upload.size > MAX_ARCHIVE_BYTES:
        raise AudioZipError("The ZIP is larger than the 200 MB upload limit.")
    if not str(upload.name).lower().endswith(".zip"):
        raise AudioZipError("Choose a .zip file.")
    try:
        upload.seek(0)
        with zipfile.ZipFile(upload) as archive:
            count = len(_audio_entries(archive))
    except AudioZipError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise AudioZipError("That file could not be read as a valid ZIP archive.") from error
    finally:
        upload.seek(0)
    return count


def _key(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def _build_plan(entries):
    sections = list(Section.objects.order_by("order", "name", "pk"))
    sections_by_name = {}
    for section in sections:
        sections_by_name.setdefault(_key(section.name), []).append(section)

    recitals = list(Recital.objects.select_related("section").order_by("order", "pk"))
    recitals_by_section_title = {}
    recitals_by_title = {}
    for recital in recitals:
        title_key = _key(recital.title)
        recitals_by_section_title.setdefault((recital.section_id, title_key), []).append(recital)
        recitals_by_title.setdefault(title_key, []).append(recital)

    plan = []
    seen_targets = {}
    for info, path, suffix in entries:
        filename = path.name
        title = path.stem.strip()
        title_key = _key(title)
        problem = ""
        section = None
        existing = None

        folder_sections = []
        for part in path.parts[:-1]:
            folder_sections.extend(sections_by_name.get(_key(part), []))
        folder_sections = list({item.pk: item for item in folder_sections}.values())

        if len(folder_sections) > 1:
            problem = "The archive path names more than one section."
        elif folder_sections:
            section = folder_sections[0]
            matches = recitals_by_section_title.get((section.pk, title_key), [])
            if len(matches) > 1:
                problem = "More than one recital in this section has the same title."
            elif matches:
                existing = matches[0]
        else:
            title_matches = recitals_by_title.get(title_key, [])
            section_matches = sections_by_name.get(title_key, [])
            if len(title_matches) == 1:
                existing = title_matches[0]
                section = existing.section
                title = existing.title
                title_key = _key(title)
            elif len(title_matches) > 1:
                problem = "This filename matches recitals in more than one section; put it in a section folder."
            elif len(section_matches) == 1:
                section = section_matches[0]
                title = section.name
                title_key = _key(title)
            elif len(section_matches) > 1:
                problem = "More than one section has this name. Put the file in a section folder."
            else:
                problem = "Put this file in a folder named after its section, or name it after an existing recital."

        if not title or len(title) > 150:
            problem = "The audio filename must have a title between 1 and 150 characters."
        if section is not None and not problem:
            target = (section.pk, title_key)
            if target in seen_targets:
                problem = f"This audio and {seen_targets[target]} both map to the same recital."
            else:
                seen_targets[target] = filename

        plan.append({
            "info": info,
            "suffix": suffix,
            "filename": filename,
            "title": title,
            "section": section,
            "existing": existing,
            "problem": problem,
        })
    return plan


def _save_recital_audio(item, data, next_order):
    section = item["section"]
    recital = item["existing"]
    created = recital is None
    old_name = recital.audio_file.name if recital and recital.audio_file else ""
    saved_name = ""

    try:
        with transaction.atomic():
            if created:
                recital = Recital.objects.create(
                    section=section,
                    title=item["title"],
                    order=next_order[section.pk],
                )
                next_order[section.pk] += 1

            filename = f"{slugify(recital.title)[:100] or 'recital-audio'}{item['suffix']}"
            recital.audio_file.save(filename, ContentFile(data), save=False)
            saved_name = recital.audio_file.name
            recital.audio_url = ""
            recital.save(update_fields=["audio_file", "audio_url"])
    except Exception:
        if saved_name:
            try:
                recital.audio_file.storage.delete(saved_name)
            except Exception:
                logger.exception("Could not remove recital audio after a failed ZIP import")
        raise

    if old_name and old_name != saved_name and not Recital.objects.filter(audio_file=old_name).exists():
        try:
            recital.audio_file.storage.delete(old_name)
        except Exception:
            logger.warning("Could not remove replaced recital audio %s", old_name, exc_info=True)

    return recital, created


def import_audio_zip(upload):
    """Save ZIP audios to matching recitals, creating missing titles in sections."""
    inspect_audio_zip(upload)
    results = []
    with zipfile.ZipFile(upload) as archive:
        plan = _build_plan(_audio_entries(archive))
        max_order = {
            section.pk: (Recital.objects.filter(section=section).order_by("-order").values_list("order", flat=True).first() or 0) + 1
            for section in Section.objects.all()
        }
        for item in plan:
            result = {
                "filename": item["filename"],
                "section": item["section"].name if item["section"] else "—",
                "recital": item["existing"].title if item["existing"] else item["title"],
                "status": "skipped",
                "message": item["problem"],
            }
            if item["problem"]:
                results.append(result)
                continue
            try:
                data = archive.read(item["info"])
                if not data:
                    raise AudioZipError("This audio file is empty.")
                recital, created = _save_recital_audio(item, data, max_order)
                result.update({
                    "recital": recital.title,
                    "recital_id": recital.pk,
                    "status": "created" if created else "updated",
                    "message": "A recital was created and the audio attached." if created else "Audio attached to the existing recital.",
                })
            except Exception:
                logger.exception("Assembly Recitals audio ZIP failed for %s", item["filename"])
                result["status"] = "failed"
                result["message"] = "The audio could not be saved. Check storage and try this file again."
            results.append(result)
    return results
