"""
One zip per level, for flash drives: everything a school needs to install
that level on any computer with no internet.

    Diction Masters - Level 1/
        Install on Windows 10 or 11.exe
        Install on Windows 7 or 8.exe
        Diction Masters (Ubuntu, Debian).deb
        Diction Masters (other Linux).AppImage
        videos/                 the level's videos, sealed
        READ ME.txt

A level with its videos is too big for one installer (Windows installers
stop at 2 GB), so the installers carry the pages, pictures and recordings,
and the videos sit beside them: the Windows installer copies them in, and
the app loads them from beside itself (the dictionmasters-desktop project).

The installers come from GitHub (DESKTOP_INSTALLERS_URL: the app's "Build
installers" run for that level), with the level's list (manifest) they were
built from: the videos packed are exactly the ones in that list, read from
storage (desktop-content/blobs, where the lessons release keeps them). The
zip is kept in storage under desktop-bundles/, and downloaded from there
(views.bundle_download), not through this server.
"""

import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.utils import timezone

from .export import blob_path
from .models import DesktopBundle

ROOT = "desktop-bundles"
INSTALLERS = [
    # (file on GitHub, its name in the zip)
    ("DictionMasters-{slug}-Setup.exe", "Install on Windows 10 or 11.exe"),
    ("DictionMasters-{slug}-Setup-Windows7-8.exe", "Install on Windows 7 or 8.exe"),
    ("DictionMasters-{slug}-linux-amd64.deb", "Diction Masters (Ubuntu, Debian).deb"),
    ("DictionMasters-{slug}-linux-x86_64.AppImage", "Diction Masters (other Linux).AppImage"),
]
READ_ME = """Diction Masters - {level}
{rule}

Everything for {level}, for any computer. No internet is needed, ever.
Copy this whole folder to the computer, or install straight from the flash drive.

1. Install. Keep the "videos" folder next to the installer: it copies the videos in.

   Windows 10 or 11 .... double-click  "Install on Windows 10 or 11.exe"
   Windows 7 or 8 ...... double-click  "Install on Windows 7 or 8.exe"
   Ubuntu, Debian ...... double-click  "Diction Masters (Ubuntu, Debian).deb"
                         then, in the app: Help > Load videos from a folder,
                         and choose this folder's "videos".
   Other Linux ......... keep "Diction Masters (other Linux).AppImage" next to
                         "videos", make it executable, and double-click it.

   If Windows says "Windows protected your PC": click More info, then Run anyway.

2. Open Diction Masters. It shows this computer's number, like K7QX-3MPA.

3. Send that number to Diction Masters. You'll get an unlock code made for
   this computer. Type it in, and every lesson and video opens.

The code works on that computer only: every computer has its own number.
"""


def slug(level):
    """As the app's build names its files: "Level 1" -> "Level-1"."""
    return re.sub(r"[^A-Za-z0-9]+", "-", level)


def _download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": "DictionMasters-Bundles/1"})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle, 4 * 1024 * 1024)
    return target


def _videos(manifest, level):
    """{blob: size} of the level's videos, from the list its installers were built from."""
    group = (manifest.get("levels") or {}).get(level)
    if not group:
        raise ValueError(f"The installers' list has no {level}.")
    return {entry["b"]: entry["s"] for entry in group["files"].values() if str(entry.get("t", "")).startswith("video/")}


def build(bundle, log=None):
    """Pack one level's zip and keep it in storage."""
    log = log or (lambda text: None)

    def say(text):
        DesktopBundle.objects.filter(pk=bundle.pk).update(progress=text[:200])
        log(text)

    bundle.status = DesktopBundle.Status.BUILDING
    bundle.error = ""
    bundle.save(update_fields=["status", "error"])
    name = slug(bundle.level)
    work = tempfile.mkdtemp(prefix="dm-bundle-")
    try:
        base = settings.DESKTOP_INSTALLERS_URL
        say("Fetching the level's list from GitHub")
        try:
            listed = _download(f"{base}/DictionMasters-{name}-manifest.json", os.path.join(work, "manifest.json"))
        except Exception as error:
            raise RuntimeError(f"No installers for {bundle.level} on GitHub yet ({error}). "
                               f"Run Actions > Build installers for {bundle.level} first.")
        with open(listed, encoding="utf-8") as handle:
            videos = _videos(json.load(handle), bundle.level)

        folder = f"Diction Masters - {bundle.level}"
        target = os.path.join(work, f"Diction-Masters-{name}.zip")
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as packed:
            for remote, local_name in INSTALLERS:
                file = remote.format(slug=name)
                say(f"Fetching {file}")
                path = _download(f"{base}/{file}", os.path.join(work, file))
                packed.write(path, f"{folder}/{local_name}")
                os.remove(path)
            for number, blob in enumerate(sorted(videos), 1):
                say(f"Packing videos: {number} of {len(videos)}")
                with default_storage.open(blob_path(blob), "rb") as source, \
                        packed.open(f"{folder}/videos/{blob}", "w", force_zip64=True) as dest:
                    shutil.copyfileobj(source, dest, 4 * 1024 * 1024)
            rule = "=" * len(f"Diction Masters - {bundle.level}")
            packed.writestr(f"{folder}/READ ME.txt",
                            READ_ME.format(level=bundle.level, rule=rule).replace("\n", "\r\n"))

        say("Saving the zip")
        stored = f"{ROOT}/Diction-Masters-{name}.zip"
        if default_storage.exists(stored):
            default_storage.delete(stored)
        with open(target, "rb") as handle:
            stored = default_storage.save(stored, File(handle, name=os.path.basename(target)))
        bundle.file = stored
        bundle.size = os.path.getsize(target)
        bundle.videos = len(videos)
        bundle.status = DesktopBundle.Status.READY
        bundle.progress = "Done"
    except Exception as error:
        bundle.status = DesktopBundle.Status.FAILED
        bundle.error = str(error)[:2000]
        bundle.progress = "Failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)
        bundle.finished_at = timezone.now()
        bundle.save()
    return bundle
