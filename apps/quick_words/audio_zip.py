"""Safely import word-named audio files from a ZIP into Quick Words."""

import logging
import stat
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.db import close_old_connections, transaction
from django.utils import timezone

from .ipa_dict import get_ipa
from .lookup import LookupUnavailable, is_lookup_candidate, lookup
from .models import QuickWord, QuickWordAudioImportJob

logger = logging.getLogger(__name__)

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_AUDIO_FILES = 300
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
LOOKUP_INTERVAL_SECONDS = 3.1
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".webm"}
_import_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quick-words-zip")


class AudioZipError(ValueError):
    """The archive is invalid, too large, or has no supported audio files."""


class WordImportSkipped(ValueError):
    """This file should be reported as skipped rather than as an import failure."""


def _audio_entries(archive):
    entries = []
    total_size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        basename = path.name
        suffix = PurePosixPath(basename).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            continue
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            continue
        if info.flag_bits & 0x1:
            raise AudioZipError(f"{basename} is password protected. Please upload an unprotected ZIP.")
        if info.file_size > MAX_AUDIO_BYTES:
            raise AudioZipError(f"{basename} is larger than the 50 MB per-audio limit.")
        total_size += info.file_size
        if total_size > MAX_UNPACKED_BYTES:
            raise AudioZipError("The ZIP expands beyond the 600 MB total audio limit.")
        entries.append((info, PurePosixPath(basename).stem, suffix, basename))
        if len(entries) > MAX_AUDIO_FILES:
            raise AudioZipError(f"The ZIP contains more than {MAX_AUDIO_FILES} audio files.")
    if not entries:
        raise AudioZipError("The ZIP has no supported audio files.")
    return entries


def inspect_audio_zip(upload):
    """Validate the archive without extracting it and return its audio count."""
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


def _save_audio(word, suffix, data, is_new=False, ipa_update=False):
    old_name = word.audio_file.name if word.audio_file else ""
    saved_name = ""
    fields = ["audio_file", "audio_url"]
    try:
        with transaction.atomic():
            if is_new:
                word.save()
            elif ipa_update:
                word.ipa = ipa_update
                fields.append("ipa")
            word.audio_file.save(
                f"{word.slug}{suffix}", ContentFile(data), save=False
            )
            saved_name = word.audio_file.name
            # A newly uploaded local clip replaces a previous hosted URL.
            word.audio_url = ""
            word.save(update_fields=fields)
    except Exception:
        if saved_name:
            try:
                word.audio_file.storage.delete(saved_name)
            except Exception:
                logger.exception("Could not remove an audio file after a failed Quick Words import")
        raise

    if old_name and old_name != saved_name:
        try:
            word.audio_file.storage.delete(old_name)
        except Exception:
            logger.warning("Could not remove replaced Quick Words audio %s", old_name, exc_info=True)


def _import_entry(word_name, suffix, data):
    if not is_lookup_candidate(word_name):
        raise WordImportSkipped("Use a single English word as the filename, without spaces or numbers.")

    existing = QuickWord.objects.filter(word__iexact=word_name).order_by("pk").first()
    dictionary_ipa = get_ipa(word_name)

    if existing:
        word = existing
        ipa = dictionary_ipa or word.ipa
        if not ipa:
            raise WordImportSkipped("IPA-Dict UK has no transcription for this word.")
        update_ipa = dictionary_ipa if dictionary_ipa and dictionary_ipa != word.ipa else False
        _save_audio(word, suffix, data, ipa_update=update_ipa)
        return "updated", word.word, "Audio attached to the existing Quick Word."

    if not dictionary_ipa:
        raise WordImportSkipped("IPA-Dict UK has no transcription for this filename.")

    try:
        details = lookup(word_name)
    except LookupUnavailable as error:
        raise RuntimeError(str(error)) from error
    if details is None:
        raise WordImportSkipped("OpenAI could not confirm this filename as an English word.")
    if details["word"].casefold() != word_name.casefold():
        raise WordImportSkipped(
            f"OpenAI suggested “{details['word']}”. Rename the audio file to that spelling and upload again."
        )

    # Keep the exact filename spelling as the saved word; IPA itself always
    # comes from the bundled British English IPA-Dict, never OpenAI.
    details["word"] = word_name
    details["ipa"] = dictionary_ipa
    word = QuickWord(source=QuickWord.SOURCE_AI, **details)
    _save_audio(word, suffix, data, is_new=True)
    return "created", word.word, "Created from the filename with UK IPA and OpenAI dictionary details."


def _append_result(job, filename, word, status, message):
    job.completed_files += 1
    if status == "created":
        job.created_words += 1
    elif status == "updated":
        job.updated_words += 1
    elif status == "skipped":
        job.skipped_files += 1
    else:
        job.failed_files += 1
    job.results = [*job.results, {
        "filename": filename,
        "word": word,
        "status": status,
        "message": message,
    }]
    job.save(update_fields=[
        "completed_files", "created_words", "updated_words", "skipped_files", "failed_files", "results",
    ])


def _process_import(job_id):
    close_old_connections()
    job = None
    try:
        job = QuickWordAudioImportJob.objects.get(pk=job_id)
        job.status = QuickWordAudioImportJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])

        seen = set()
        last_lookup = 0.0
        actual_total = 0
        with job.archive.open("rb") as uploaded, zipfile.ZipFile(uploaded) as archive:
            entries = _audio_entries(archive)
            for info, word_name, suffix, filename in entries:
                try:
                    if not is_lookup_candidate(word_name):
                        raise WordImportSkipped("Use a single English word as the filename, without spaces or numbers.")
                    folded = word_name.casefold()
                    if folded in seen:
                        raise WordImportSkipped("Another audio file in this ZIP already uses this word name.")
                    seen.add(folded)

                    data_limit = min(MAX_AUDIO_BYTES, MAX_UNPACKED_BYTES - actual_total) + 1
                    with archive.open(info) as audio_file:
                        data = audio_file.read(data_limit)
                    if not data or len(data) > MAX_AUDIO_BYTES or len(data) != info.file_size:
                        raise WordImportSkipped("The audio file is empty, damaged, or larger than the upload limit.")
                    actual_total += len(data)
                    if actual_total > MAX_UNPACKED_BYTES:
                        raise AudioZipError("The ZIP expands beyond the 600 MB total audio limit.")

                    existing = QuickWord.objects.filter(word__iexact=word_name).exists()
                    if not existing and get_ipa(word_name):
                        delay = LOOKUP_INTERVAL_SECONDS - (time.monotonic() - last_lookup)
                        if delay > 0:
                            time.sleep(delay)
                        last_lookup = time.monotonic()

                    status, saved_word, message = _import_entry(word_name, suffix, data)
                except WordImportSkipped as error:
                    status, saved_word, message = "skipped", word_name, str(error)
                except (LookupUnavailable, RuntimeError) as error:
                    status, saved_word, message = "failed", word_name, str(error)
                except AudioZipError:
                    raise
                except Exception:
                    logger.exception("Quick Words audio import failed for %s", filename)
                    status, saved_word, message = "failed", word_name, "This file could not be imported. Check the server log for details."
                _append_result(job, filename, saved_word, status, message)

        job.status = QuickWordAudioImportJob.Status.COMPLETE
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
    except Exception:
        logger.exception("Quick Words ZIP import job %s failed", job_id)
        if job is not None:
            job.status = QuickWordAudioImportJob.Status.FAILED
            job.error = "The ZIP import stopped unexpectedly. Completed entries remain saved."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error", "finished_at"])
    finally:
        if job is not None and job.archive:
            try:
                job.archive.delete(save=False)
                job.archive = ""
                job.save(update_fields=["archive"])
            except Exception:
                logger.exception("Could not remove the Quick Words import ZIP for job %s", job_id)
        close_old_connections()


def start_audio_zip_import(job_id):
    """Queue an accepted import so many OpenAI lookups do not hold a web request open."""
    _import_pool.submit(_process_import, str(job_id))
