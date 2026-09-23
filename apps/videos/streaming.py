"""
Passing a video through from private storage, a piece at a time.

Storage (Cloudflare R2, or the local folder in development) is never
opened to the public. Django reads the part of the file the player asks
for and sends it on, so seeking works exactly as it would from a normal
address, while the real one stays out of the browser.
"""

import logging
import re

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseNotModified, StreamingHttpResponse

logger = logging.getLogger(__name__)

CHUNK = 512 * 1024
RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def brief_link(field):
    """A link straight to storage that stops working in minutes, or "" if
    this storage has no such thing (a local folder, say).

    The page itself never carries this: it is handed out one request at a
    time, after Django has checked who is asking."""
    storage = field.storage
    if getattr(storage, "bucket", None) is None:
        return ""
    seconds = int(getattr(settings, "VIDEO_LINK_SECONDS", 15 * 60))
    try:
        return storage.url(field.name, expire=seconds)
    except TypeError:                     # a storage that doesn't take an expiry
        return storage.url(field.name)
    except Exception:                     # storage trouble: fall back to passing it through
        logger.exception("Couldn't sign a link for %s", field.name)
        return ""


def _key_in_bucket(storage, name):
    """Where the file sits in the bucket, including any folder the
    storage keeps everything under (settings' "location")."""
    prefix = (getattr(storage, "location", "") or "").strip("/")
    return f"{prefix}/{name}".lstrip("/") if prefix else name


def _read_from_storage(field, start, length):
    """Bytes from the file, in pieces, without holding it all in memory."""
    storage = field.storage
    bucket = getattr(storage, "bucket", None)
    if bucket is not None:
        # R2 (or any S3 storage): ask for exactly the range wanted.
        key = _key_in_bucket(storage, field.name)
        body = bucket.Object(key).get(Range=f"bytes={start}-{start + length - 1}")["Body"]
        while True:
            piece = body.read(CHUNK)
            if not piece:
                break
            yield piece
        body.close()
        return
    handle = storage.open(field.name, "rb")
    try:
        handle.seek(start)
        left = length
        while left > 0:
            piece = handle.read(min(CHUNK, left))
            if not piece:
                break
            left -= len(piece)
            yield piece
    finally:
        handle.close()


def _wanted(header, size):
    """The piece of the file the player asked for: (start, length), or
    None for the whole thing."""
    match = RANGE.match(header or "")
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if first == "":
        # "the last N bytes"
        length = min(int(last or 0), size)
        return (size - length, length) if length else None
    start = min(int(first), size - 1)
    end = min(int(last), size - 1) if last else size - 1
    if end < start:
        return None
    return start, end - start + 1


def serve(request, field, *, content_type="video/mp4", filename=None, as_download=False):
    """Send a stored file to this request, honouring Range so the player
    can seek, and never revealing where the file really is."""
    size = field.size
    tag = f'"{abs(hash((field.name, size)))}"'
    if request.headers.get("If-None-Match") == tag:
        return HttpResponseNotModified()

    piece = _wanted(request.headers.get("Range"), size)
    if piece is None:
        response = StreamingHttpResponse(_read_from_storage(field, 0, size), content_type=content_type)
        response["Content-Length"] = str(size)
        status_headers = {}
    else:
        start, length = piece
        response = StreamingHttpResponse(_read_from_storage(field, start, length), status=206,
                                         content_type=content_type)
        response["Content-Length"] = str(length)
        status_headers = {"Content-Range": f"bytes {start}-{start + length - 1}/{size}"}

    for name, value in status_headers.items():
        response[name] = value
    response["Accept-Ranges"] = "bytes"
    response["ETag"] = tag
    # Belongs to one signed-in person: no shared cache may keep it.
    response["Cache-Control"] = "private, max-age=0, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if as_download and filename:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


__all__ = ["serve", "FileResponse", "HttpResponse"]
