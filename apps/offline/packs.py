"""
Building a lesson pack: every picture, recording and video one level uses
(the same list the app syncs, apps/offline/catalog.py), encrypted, in one
file to copy to a flash drive. The app loads it from "Load from a file" on
the Offline lessons page (static/js/offline_pack.js) instead of downloading.

The file (".dmpack"):

    b"DMPACK1\\n"
    the files, each in pieces of up to 4 MB, each piece sealed on its own with
    AES-256-GCM and the pack's key (LessonPack.key)
    the index, as JSON: where each file's pieces are, and what it is
    8 bytes: the index's length (big-endian)

    index = {"level", "built", "pack", "files": [{"k", "t", "size", "parts"}],
             "videos": [{"ref", "title", "t", "size", "parts"}]}
    parts = [[offset, length, iv (base64)], ...]

"k" is the address the app keeps a file under (templates/pwa/sw.js,
mediaKey): the full address for a file in storage, or just the path for one
served by this site. The index isn't secret: it says where things are, not
what's in them.

Run by `manage.py build_lesson_pack <id>` in its own process, started from
the control room, so a long build survives the web server restarting.
"""

import base64
import json
import mimetypes
import os
import struct
import tempfile
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.files import File
from django.core.files.storage import default_storage
from django.utils import timezone

from .models import LessonPack

MAGIC = b"DMPACK1\n"
PIECE = 4 * 1024 * 1024


def new_key():
    return base64.b64encode(os.urandom(32)).decode()


def media_key(name):
    """The address the app keeps this stored file under."""
    parts = urlsplit(default_storage.url(name))
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.path


def _contents(level):
    """(pictures and audio, videos) for a pupil on this level."""
    from apps.accounts.models import User
    from apps.learning_tools.views import tools_for

    from .catalog import build

    shelf = build([level], {tool["url_name"] for tool in tools_for(User(role="student", level=level))})
    videos = {name: (ref, title) for ref, name, title in shelf.video_files}
    return sorted(shelf.files), sorted(videos.items())


def _seal_into(out, cipher, source):
    """Write one stored file into the pack, piece by piece; its parts."""
    parts = []
    while True:
        piece = source.read(PIECE)
        if not piece:
            return parts
        iv = os.urandom(12)
        sealed = cipher.encrypt(iv, piece, None)
        parts.append([out.tell(), len(sealed), base64.b64encode(iv).decode()])
        out.write(sealed)


def build(pack, progress_every=25):
    """Build this pack's file and keep it in storage. Older ready packs for
    the same level are removed once this one is ready."""
    pack.status = LessonPack.Status.BUILDING
    pack.save(update_fields=["status"])
    cipher = AESGCM(base64.b64decode(pack.key))
    files, videos = _contents(pack.level)
    pack.files_total = len(files) + len(videos)
    pack.save(update_fields=["files_total"])

    index = {"level": pack.level, "built": timezone.now().isoformat(), "pack": pack.pk, "files": [], "videos": []}
    with tempfile.NamedTemporaryFile(suffix=".dmpack", delete=False) as out:
        path = out.name
    try:
        with open(path, "wb") as out:
            out.write(MAGIC)
            done = 0
            for name in files:
                entry = _add(out, cipher, name, pack)
                if entry:
                    index["files"].append({"k": media_key(name), **entry})
                done += 1
                if done % progress_every == 0:
                    LessonPack.objects.filter(pk=pack.pk).update(files_done=done, missing=pack.missing)
            for name, (ref, title) in videos:
                entry = _add(out, cipher, name, pack)
                if entry:
                    index["videos"].append({"ref": ref, "title": title, **entry})
                done += 1
                LessonPack.objects.filter(pk=pack.pk).update(files_done=done, missing=pack.missing)
            raw = json.dumps(index, separators=(",", ":")).encode()
            out.write(raw)
            out.write(struct.pack(">Q", len(raw)))
        with open(path, "rb") as built:
            pack.file.save(f"{pack.level.lower().replace(' ', '-')}-{pack.pk}.dmpack", File(built), save=False)
    finally:
        os.unlink(path)

    pack.size = pack.file.size
    pack.files_done = pack.files_total
    pack.videos = len(index["videos"])
    pack.status = LessonPack.Status.READY
    pack.finished_at = timezone.now()
    pack.save()
    for older in LessonPack.objects.filter(level=pack.level, status=LessonPack.Status.READY).exclude(pk=pack.pk):
        if older.file:
            older.file.delete(save=False)
        older.delete()
    return pack


def _add(out, cipher, name, pack):
    """One stored file into the pack: {"t", "size", "parts"}, or None if
    storage hasn't got it (counted, and the build carries on)."""
    try:
        with default_storage.open(name, "rb") as source:
            parts = _seal_into(out, cipher, source)
    except (FileNotFoundError, OSError):
        pack.missing += 1
        return None
    size = sum(length - 16 for _offset, length, _iv in parts)       # less each piece's 16-byte tag
    return {"t": mimetypes.guess_type(name)[0] or "application/octet-stream", "size": size, "parts": parts}


def read_index(raw):
    """The index of a pack file's bytes (for tests and checks)."""
    assert raw[:len(MAGIC)] == MAGIC, "not a lesson pack"
    (length,) = struct.unpack(">Q", raw[-8:])
    return json.loads(raw[-8 - length:-8])
