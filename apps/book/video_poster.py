"""
Thumbnails for uploaded video, taken from the video itself with ffmpeg.

A video with no poster opens as a black rectangle, which looks broken to
a child. So a frame a little way in — past the fade-up most recordings
start with — is grabbed, shrunk, and saved as the poster.

The frame is read straight from wherever the video lives. For a file on
R2 that means a couple of ranged requests rather than downloading the
whole video, so a long lesson costs about as much as a short one.

It runs in the background when a video is saved, so uploading never
waits for it, and it never replaces a poster an admin uploaded
themselves. If ffmpeg isn't installed the site simply carries on with no
posters — see thumbnails_available().
"""

import logging
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from django.core.files.base import ContentFile
from django.db import close_old_connections

logger = logging.getLogger(__name__)

# Far enough in to miss a fade from black, early enough to be on screen
# in even a short clip.
FRAME_AT_SECONDS = 2.0
FALLBACK_SECONDS = 0.3
POSTER_WIDTH = 1280
TIMEOUT_SECONDS = 60
MIN_BYTES = 800

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-poster")
_busy = threading.Lock()


def thumbnails_available():
    return bool(shutil.which("ffmpeg"))


def _grab(source, at):
    """One JPEG frame from `source` (a path or a URL), or None."""
    with tempfile.NamedTemporaryFile(suffix=".jpg") as out:
        command = [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-ss", str(at),                      # before -i: ffmpeg seeks, not decodes
            "-i", source,
            "-frames:v", "1",
            "-vf", f"scale={POSTER_WIDTH}:-2:force_original_aspect_ratio=decrease",
            "-q:v", "3",
            out.name,
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            logger.warning("No frame at %ss from %s: %s", at, source[:80], error)
            return None
        out.seek(0)
        data = out.read()
    return data if len(data) > MIN_BYTES else None


def _source_for(instance):
    """Where ffmpeg should read this video from: the stored file's URL
    (signed, for R2) or the local path, or the video URL as given."""
    if instance.video_file:
        try:
            return instance.video_file.path      # local storage
        except (NotImplementedError, ValueError):
            return instance.video_file.url       # R2 and other remote storage
    return instance.video_url or ""


def make_poster(instance, replace=False, save=True):
    """Give one object its poster. Returns True if a poster was saved."""
    if not hasattr(instance, "video_poster") or not thumbnails_available():
        return False
    if instance.video_poster and not replace:
        return False

    source = _source_for(instance)
    if not source:
        return False
    # A YouTube or Vimeo page isn't a video file; those services show
    # their own thumbnail in the embed.
    if source.startswith("http") and any(host in source for host in ("youtube.", "youtu.be", "vimeo.")):
        return False

    frame = _grab(source, FRAME_AT_SECONDS) or _grab(source, FALLBACK_SECONDS)
    if frame is None:
        return False

    old = instance.video_poster.name if instance.video_poster else ""
    name = f"poster-{instance._meta.model_name}-{instance.pk}.jpg"
    instance.video_poster.save(name, ContentFile(frame), save=False)
    if save:
        instance.__class__.objects.filter(pk=instance.pk).update(video_poster=instance.video_poster.name)
    if old and old != instance.video_poster.name:
        instance.video_poster.storage.delete(old)
    return True


def poster_in_background(instance):
    """Make this object's poster without holding up the upload."""
    if not thumbnails_available() or instance.video_poster or not _source_for(instance):
        return False

    model = instance.__class__
    pk = instance.pk

    def run():
        close_old_connections()
        try:
            fresh = model.objects.filter(pk=pk).first()
            if fresh:
                make_poster(fresh)
        except Exception:                      # a thumbnail is never worth an error page
            logger.exception("Couldn't make a poster for %s %s", model.__name__, pk)
        finally:
            close_old_connections()

    _pool.submit(run)
    return True


def video_models():
    """Every model that has a video and can hold a poster."""
    from django.apps import apps

    return [m for m in apps.get_models() if any(f.name == "video_poster" for f in m._meta.fields)]


def missing_posters():
    """(model, queryset) for objects with a video but no poster."""
    from django.db.models import Q

    rows = []
    for model in video_models():
        found = model.objects.filter(video_poster="").filter(~Q(video_file="") | ~Q(video_url=""))
        if found.exists():
            rows.append((model, found))
    return rows


def fill_missing():
    made = 0
    for _model, found in missing_posters():
        for instance in found:
            if make_poster(instance):
                made += 1
    return made


def fill_missing_in_background():
    if not thumbnails_available() or not missing_posters():
        return False
    if not _busy.acquire(blocking=False):
        return False

    def run():
        close_old_connections()
        try:
            fill_missing()
        finally:
            close_old_connections()
            _busy.release()

    _pool.submit(run)
    return True
