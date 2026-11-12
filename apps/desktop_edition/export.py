"""
Building a release of the lessons for the offline computer app.

    manage.py export_desktop_content                 every level
    manage.py export_desktop_content --levels "Level 1,Level 2" --no-videos

For each level, the lesson pages are rendered exactly as a pupil of that
level sees them on the website, from the same list the website's own
offline mode keeps (apps/offline/catalog.py: add a learning tool there and
it reaches the computer app too). Each page is rendered as a hidden
"desktop export" pupil of that level, made the first time; their name on
the pages is a placeholder the app swaps for the learner's own.

Then everything the pages use is gathered: the site's styles, scripts and
pictures (all of static/), every picture, recording and video from storage,
and any recording or picture the lessons link to on another website. Their
addresses in the pages are changed to the app's own, so nothing needs the
internet.

For activities, the answers are written out too (answers_for), so the app
marks them itself with the same rules as the website (apps/echospell/marking.py).

Everything is sealed (keys.py) and kept in storage under desktop-content/,
each file under a name made from its contents: a file that hasn't changed
is never uploaded again, and an installed app downloads only what's new.
The list of the release (its "manifest") says which file is which.
"""

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http.request import validate_host
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from . import keys, unlock
from .models import ContentRelease

logger = logging.getLogger(__name__)

ROOT = "desktop-content"
FORMAT = 1
LEARNER_PLACEHOLDER = "DMLEARNER"
EXPORT_EMAIL_DOMAIN = "desktop-export.invalid"
USER_AGENT = "Mozilla/5.0 (DictionMastersApp/desktop; DictionMastersEdition/offline)"

# Files on other websites that lessons link to and that are worth keeping.
# Anything else (YouTube, a web page) stays a link that needs the internet.
LINKED_MEDIA = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".aac", ".mp4", ".webm", ".m4v", ".mov",
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
LINKED_MEDIA_MAX = 300 * 1024 * 1024

_ABSOLUTE = re.compile(r"""https?://[^\s"'<>()\\`]+""")
_CSRF = re.compile(r"""csrfmiddlewaretoken["']?\s+value=["']([A-Za-z0-9]{32,64})["']""")


def steady(html):
    """The page without what changes on every render (the security token in
    forms, which the app doesn't use), so an unchanged page is never sent
    to the apps again."""
    for token in set(_CSRF.findall(html)):
        html = html.replace(token, "desktop")
    # A lesson video's ticket (for saving it on the website) changes on every
    # render; the app plays the copy in the release instead (Media.rewrite).
    html = re.sub(r"""data-ticket=(["'])[^"']*\1""", 'data-ticket=""', html)
    # Daily practice's "Give me a new set" link carries a random seed.
    return re.sub(r"\?shuffle=[0-9a-f]{32}", "?shuffle=desktop", html)


def blob_path(blob):
    return f"{ROOT}/blobs/{blob[:2]}/{blob}"


def manifest_path(number):
    return f"{ROOT}/releases/{number}.json"


def read_manifest(release):
    if not release or not release.manifest:
        return None
    with default_storage.open(release.manifest, "rb") as handle:
        return json.loads(handle.read())


# ------------------------------------------------------------ who renders

def export_user(level):
    """The hidden pupil a level's pages are rendered as: a student of that
    level with no school, so their pages show that level's work and
    nothing else. Their plan never ends, and they can't sign in."""
    from apps.accounts.models import User
    from apps.billing.access import subscription_for

    slug = re.sub(r"[^a-z0-9]+", "-", level.lower()).strip("-")
    user, made = User.objects.get_or_create(
        email=f"level-{slug}@{EXPORT_EMAIL_DOMAIN}",
        defaults={"first_name": LEARNER_PLACEHOLDER, "role": User.Role.STUDENT, "level": level, "is_active": True},
    )
    if made:
        user.set_unusable_password()
        user.save()
    elif user.level != level or user.first_name != LEARNER_PLACEHOLDER:
        user.level, user.first_name = level, LEARNER_PLACEHOLDER
        user.save()
    subscription = subscription_for(user)
    if subscription is not None:
        far = timezone.now() + timezone.timedelta(days=365 * 50)
        if not subscription.paid_until or subscription.paid_until < far - timezone.timedelta(days=365):
            subscription.paid_until = far
            subscription.save()
    return user


def is_export_user(user):
    return str(getattr(user, "email", "")).endswith("@" + EXPORT_EMAIL_DOMAIN)


def _host():
    host = urlsplit(settings.SITE_URL).hostname or "localhost"
    allowed = list(settings.ALLOWED_HOSTS)
    if settings.DEBUG and not allowed:
        allowed = [".localhost", "127.0.0.1", "[::1]"]
    for candidate in (host, "localhost", "127.0.0.1"):
        if validate_host(candidate, allowed):
            return candidate
    return host


# ------------------------------------------------------------- the pages

def pages_for(user):
    """[{"p": path, "v": version}] this pupil's app would keep."""
    from apps.learning_tools.views import tools_for
    from apps.offline.catalog import _library, build

    tools = {tool["url_name"] for tool in tools_for(user)}
    shelf = build([user.level], tools)
    return shelf.pages + _library(user, tools), tools


def _path_of(url, base="/"):
    """A same-site address as "/path/?query", or None for another site."""
    full = urlsplit(urljoin(base, url))
    if full.netloc and full.hostname not in {_host(), urlsplit(settings.SITE_URL).hostname, "testserver"}:
        return None
    return full.path + (f"?{full.query}" if full.query else "")


class Media:
    """Every file the pages use, and the app's address for each."""

    def __init__(self, fetch_linked=True):
        self.fetch_linked = fetch_linked
        self.wanted = {}           # app address -> ("storage", name) | ("web", url)
        self.failed = {}
        probe = default_storage.url("__probe__")
        split = urlsplit(probe)
        self.storage_prefix = (f"{split.scheme}://{split.netloc}" if split.scheme else "") + split.path[: -len("__probe__")]
        self.site_hosts = {_host(), urlsplit(settings.SITE_URL).hostname, "testserver"}

    def _stored(self, name):
        address = "/_m/" + quote(name)
        self.wanted.setdefault(address, ("storage", name))
        return address

    def address_for(self, raw):
        """The app's address for one address found in a page, or None to
        leave it as it is."""
        url = unescape(raw)
        split = urlsplit(url)
        canon = f"{split.scheme}://{split.netloc}{split.path}" if split.scheme else split.path
        if self.storage_prefix and canon.startswith(self.storage_prefix) and len(canon) > len(self.storage_prefix):
            return self._stored(unquote(canon[len(self.storage_prefix):]))
        if split.scheme and split.hostname in self.site_hosts:
            return split.path + (f"?{split.query}" if split.query else "")
        if split.hostname == "fonts.googleapis.com" and split.path.startswith("/css") and self.fetch_linked:
            # The site's typefaces: kept, with their font files (_fonts).
            address = f"/_x/fonts-{hashlib.sha256(url.encode()).hexdigest()[:24]}.css"
            self.wanted.setdefault(address, ("fonts", url))
            return address
        if split.scheme and self.fetch_linked and os.path.splitext(split.path)[1].lower() in LINKED_MEDIA:
            if url in self.failed:
                return None
            ext = os.path.splitext(split.path)[1].lower()
            address = f"/_x/{hashlib.sha256(url.encode()).hexdigest()[:24]}{ext}"
            self.wanted.setdefault(address, ("web", url))
            return address
        return None

    def _video_address(self, ticket):
        from apps.videos import links

        found = links.read_ticket(unescape(ticket), links.WATCH)
        video = links.video_from_ticket(found) if found else None
        stored = getattr(video, "video_file", None) if video is not None else None
        return self._stored(stored.name) if stored else None

    def rewrite(self, html):
        """The page with every file address it uses changed to the app's."""
        def swap(match):
            found = match.group(0)
            trailing = ""
            while found and found[-1] in ".,;":              # the end of a sentence, not of the address
                trailing, found = found[-1] + trailing, found[:-1]
            address = self.address_for(found)
            return (address if address is not None else found) + trailing

        html = _ABSOLUTE.sub(swap, html)
        # Lesson videos: the stored file the ticket stands for, kept like any
        # recording, so the video plays with no internet.
        html = _PLAY.sub(lambda match: self._video_address(match.group(1)) or match.group(0), html)
        media_url = settings.MEDIA_URL or ""
        if media_url.startswith("/") and media_url != "/":
            pattern = re.compile(r"""(?<=["'(=\s,])""" + re.escape(media_url) + r"""[^\s"'<>()\\`?#]+(?:\?[^\s"'<>()\\`]*)?""")
            html = pattern.sub(lambda m: self._stored(unquote(unescape(m.group(0)).split("?")[0][len(media_url):])), html)
        return html


# A lesson video plays from /videos/play/<ticket>/: a short-lived address the
# website gives the pupil looking at the page (apps/videos), not the file.
_PLAY = re.compile(r"""(?<=["'])/videos/play/([^/"'\s]+)/(?=["'])""")

_READ_ALONG = re.compile(r"""(?<=data-ra-sync=["'])(/book/read-along/([^/"':]+)[^"']*)(?=["'])""")


def keep_read_along(html, client, extras):
    """A read-along's word timings (the highlight that follows the voice) are
    fetched from a signed address that changes on every render. Keep the
    timings in the release under a steady address instead, so they work
    offline and the page stays the same."""
    def swap(match):
        url, payload = match.group(1), match.group(2)
        address = f"/_ra/{payload}.json"
        if address not in extras:
            try:
                data = json.loads(client.get(url).content)
            except Exception:                       # no timings: the page plays the recording without them
                data = {"status": "none", "words": []}
            data["retry"] = 0                       # offline nobody is measuring it: don't keep asking
            extras[address] = json.dumps(data).encode()
        return address

    return _READ_ALONG.sub(swap, html)


def render_level(level, media, log):
    """{path: html} and {path: where it sends you} for one level, with the
    pupil's home page."""
    user = export_user(level)
    listed, tools = pages_for(user)
    client = Client(HTTP_HOST=_host(), HTTP_USER_AGENT=USER_AGENT, HTTP_X_DM_OFFLINE_COPY="1",
                    HTTP_X_DM_DESKTOP_EDITION="1", HTTP_ACCEPT="text/html")
    client.force_login(user)
    pages, redirects, skipped, extras = {}, {}, [], {}
    queue = [page["p"] for page in listed]
    seen = set()
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            response = client.get(path)
        except Exception as error:                     # one broken page mustn't stop the release
            logger.exception("Desktop export: %s failed", path)
            skipped.append(f"{level} {path}: {type(error).__name__}: {error}"[:300])
            continue
        if response.status_code in (301, 302, 303, 307, 308):
            target = _path_of(response["Location"], path)
            if target and not target.startswith(reverse("accounts:login")):
                redirects[path] = target
                if target not in seen and len(seen) < len(listed) * 2 + 50:
                    queue.append(target)
            continue
        if response.status_code != 200 or "html" not in response.get("Content-Type", ""):
            skipped.append(f"{level} {path}: {response.status_code}")
            continue
        html = response.content.decode(response.charset or "utf-8", "replace")
        pages[path] = media.rewrite(keep_read_along(steady(html), client, extras))
        if len(pages) % 50 == 0:
            log(f"{level}: {len(pages)} pages")
    return {"home": reverse("accounts:dashboard"), "pages": pages, "redirects": redirects,
            "skipped": skipped, "tools": sorted(tools), "user": user, "extras": extras}


# ---------------------------------------------------------- the answers

def _item_data(activity, item):
    from apps.echospell.marking import alternatives
    from apps.echospell.models import _parse_lines
    from apps.manage.rich_text import plain_text

    answers = alternatives(item.answer)
    data = {"id": item.pk, "answers": answers, "first": item.first_answer}
    if activity.kind in ("listen-and-number", "listen-and-circle"):
        data["lists"] = [_parse_lines(option) for option in answers]
    if activity.kind == "word-to-sentence":
        data["word"] = plain_text(item.prompt)
    return data


def _activity_data(activity):
    kind = activity.kind_spec
    return {
        "title": str(activity.title),
        "kind": activity.kind,
        "mode": getattr(kind, "mode", "") if kind else "",
        "pass_mark": activity.pass_mark,
        "items": [_item_data(activity, item) for item in activity.items.all()],
    }


def answers_for(level, tools):
    """{the activity's page: what marking it needs} for one level. The app
    marks a learner's answers with these, offline."""
    from apps.book.programmes import programme_for
    from apps.echospell.levels import echospell_level
    from apps.echospell.models import Activity
    from apps.tricks.models import LessonActivity
    from apps.tricks.progress import lessons_in_order

    found = {}
    if "echospell:hub" in tools:
        name = echospell_level(level)
        for activity in (Activity.objects.filter(is_published=True, group__level__name=name, group__level__is_published=True)
                         .select_related("group__level").prefetch_related("items")):
            group = activity.group
            path = reverse("echospell:activity_detail", args=[group.level.slug, group.slug, activity.slug])
            found[path] = _activity_data(activity)
    for programme, tool in (("academy", "book:home"), ("tricks", "tricks:home")):
        if tool not in tools:
            continue
        info = programme_for(programme)
        lessons = {lesson.pk: lesson for lesson in lessons_in_order(programme)}
        for activity in (LessonActivity.objects.filter(is_published=True, lesson_id__in=lessons)
                         .prefetch_related("items")):
            path = reverse(info["activity"], args=[lessons[activity.lesson_id].slug, activity.slug])
            found[path] = _activity_data(activity)
    return found


# ------------------------------------------------------- the site's files

def static_files():
    """(app address, file on disk) for the site's own styles, scripts and
    pictures: the collected copy (with the names pages use in production)
    when there is one, the source folders otherwise."""
    prefix = settings.STATIC_URL if settings.STATIC_URL.startswith("/") else "/" + settings.STATIC_URL
    root = Path(settings.STATIC_ROOT) if getattr(settings, "STATIC_ROOT", None) else None
    if root and root.is_dir() and any(root.iterdir()):
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and not relative.startswith("admin/") and not relative.endswith((".gz", ".br")):
                yield prefix + relative, path
        return
    from django.contrib.staticfiles import finders

    seen = set()
    for finder in finders.get_finders():
        for relative, storage in finder.list(["admin/*", "*.scss"]):
            relative = relative.replace(os.sep, "/")
            if relative not in seen:
                seen.add(relative)
                yield prefix + relative, Path(storage.path(relative))


# --------------------------------------------------- sealing and storing

def _type(address, default="application/octet-stream"):
    return mimetypes.guess_type(address.split("?")[0])[0] or default


class Store:
    """Seals files and keeps them in storage, each once."""

    def __init__(self, known=()):
        self.known = set(known)
        self.new_size = 0
        self.size = 0

    def _keep(self, blob, sealed_file):
        if blob in self.known:
            return
        name = blob_path(blob)
        if not default_storage.exists(name):
            default_storage.save(name, sealed_file)
            self.new_size += sealed_file.size
        self.known.add(blob)

    def put_bytes(self, group, data, kind):
        blob = keys.blob_id(group, data)
        if blob not in self.known:
            self._keep(blob, ContentFile(keys.seal(data, group)))
        self.size += len(data)
        return {"b": blob, "t": kind, "s": len(data)}

    def put_file(self, group, source, kind):
        """A file that may be large (a video), from an open file: hashed
        and sealed piece by piece through a temporary file."""
        digest = hashlib.sha256(group.encode() + b"\0")
        size = 0
        with tempfile.TemporaryFile() as plain:
            while chunk := source.read(keys.PIECE):
                digest.update(chunk)
                plain.write(chunk)
                size += len(chunk)
            blob = digest.hexdigest()[:40]
            self.size += size
            if blob in self.known:
                return {"b": blob, "t": kind, "s": size}
            plain.seek(0)
            with tempfile.TemporaryFile() as sealed:
                cipher = keys.AESGCM(keys.content_key(group))
                sealed.write(keys.MAGIC + keys.struct.pack(">I", keys.PIECE))
                wrote = False
                while (piece := plain.read(keys.PIECE)) or not wrote:
                    nonce = os.urandom(12)
                    sealed.write(nonce + cipher.encrypt(nonce, piece, None))
                    wrote = True
                sealed.seek(0)
                self._keep(blob, File(sealed, name=blob))
        return {"b": blob, "t": kind, "s": size}


def _open_media(source):
    kind, where = source
    if kind == "storage":
        return default_storage.open(where, "rb")
    request = urllib.request.Request(where, headers={"User-Agent": "DictionMasters-DesktopExport/1"})
    response = urllib.request.urlopen(request, timeout=60)
    length = int(response.headers.get("Content-Length") or 0)
    if length > LINKED_MEDIA_MAX:
        response.close()
        raise OSError(f"too big ({length // 1048576} MB)")
    return response


FONT_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_FONT_FILE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)\s]+)\)")


def _fonts(url, level, store, files):
    """A Google Fonts stylesheet, with each font file it names kept beside
    it, as the stylesheet's sealed entry."""
    def get(address):
        request = urllib.request.Request(address, headers={"User-Agent": FONT_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    css = get(url).decode("utf-8", "replace")
    for font in sorted(set(_FONT_FILE.findall(css))):
        ext = os.path.splitext(urlsplit(font).path)[1] or ".woff2"
        address = f"/_x/{hashlib.sha256(font.encode()).hexdigest()[:24]}{ext}"
        if address not in files:
            files[address] = store.put_bytes(level, get(font), _type(address, "font/woff2"))
        css = css.replace(font, address)
    return store.put_bytes(level, css.encode(), "text/css")


def _is_video(address, kind):
    return kind.startswith("video/")


# ----------------------------------------------------------- one release

def build(release, log=None):
    """Build this release: render, gather, seal, store, and write its list."""
    from apps.accounts.access import LEVEL_ORDER

    log = log or (lambda text: None)

    def say(text):
        ContentRelease.objects.filter(pk=release.pk).update(progress=text[:200])
        log(text)

    release.status = ContentRelease.Status.BUILDING
    release.save(update_fields=["status"])
    levels = [part for part in release.levels.split(",") if part] or list(LEVEL_ORDER)
    previous = read_manifest(ContentRelease.latest())
    known = set()
    if previous:
        for group in [previous.get("common", {}), *previous.get("levels", {}).values()]:
            known.update(entry["b"] for entry in group.get("files", {}).values())
    store = Store(known)

    manifest = {"format": FORMAT, "release": release.pk, "built": timezone.now().isoformat(),
                "site": settings.SITE_URL, "placeholder": LEARNER_PLACEHOLDER,
                "common": {"files": {}}, "levels": {}, "level_order": unlock.LEVELS}

    say("The site's styles and scripts")
    for address, path in static_files():
        with open(path, "rb") as handle:
            manifest["common"]["files"][address] = store.put_bytes(keys.COMMON, handle.read(), _type(address))

    skipped, page_count, file_count = [], 0, len(manifest["common"]["files"])
    for level in levels:
        say(f"{level}: rendering the pages")
        media = Media()
        rendered = render_level(level, media, say)
        files = {}
        for path, html in rendered["pages"].items():
            files[path] = store.put_bytes(level, html.encode("utf-8"), "text/html; charset=utf-8")
        for address, data in rendered["extras"].items():
            files[address] = store.put_bytes(level, data, "application/json")
        answers = answers_for(level, set(rendered["tools"]))
        files["/_dm/answers.json"] = store.put_bytes(level, json.dumps(answers).encode(), "application/json")

        say(f"{level}: {len(media.wanted)} pictures, recordings and videos")
        for number, (address, source) in enumerate(sorted(media.wanted.items()), 1):
            kind = _type(address)
            if not release.include_videos and _is_video(address, kind):
                continue
            try:
                if source[0] == "fonts":
                    files[address] = _fonts(source[1], level, store, files)
                    continue
                with _open_media(source) as handle:
                    files[address] = store.put_file(level, handle, kind)
            except Exception as error:
                skipped.append(f"{level} file {source[1]}: {error}"[:300])
            if number % 25 == 0:
                say(f"{level}: files {number} of {len(media.wanted)}")

        # The level's lesson keys, locked: only a computer's unlock code opens them (unlock.py).
        manifest["levels"][level] = {"home": rendered["home"], "files": files, "redirects": rendered["redirects"],
                                     "unlock": unlock.wrap(level)}
        skipped += rendered["skipped"]
        page_count += len(rendered["pages"])
        file_count += len(files)

    say("Saving the list")
    name = manifest_path(release.pk)
    raw = json.dumps(manifest, separators=(",", ":")).encode()
    if default_storage.exists(name):
        default_storage.delete(name)
    default_storage.save(name, ContentFile(raw))
    release.manifest = name
    release.pages = page_count
    release.files = file_count
    release.size = store.size
    release.new_size = store.new_size
    release.skipped = "\n".join(skipped)[:20000]
    release.status = ContentRelease.Status.READY
    release.finished_at = timezone.now()
    release.progress = "Done"
    release.save()
    return release


def write_folder(manifest, out, fetch_blob=None):
    """Put a release in a folder, as the app's installer carries it:
    manifest.json and blobs/. Used by `export_desktop_content --to` (and by
    the app's build, which downloads the same thing over the internet)."""
    out = Path(out)
    (out / "blobs").mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_bytes(json.dumps(manifest, separators=(",", ":")).encode())
    wanted = set()
    for group in [manifest["common"], *manifest["levels"].values()]:
        wanted.update(entry["b"] for entry in group["files"].values())
    for blob in sorted(wanted):
        target = out / "blobs" / blob
        if target.exists():
            continue
        with default_storage.open(blob_path(blob), "rb") as source, open(target, "wb") as dest:
            shutil.copyfileobj(source, dest)
    return len(wanted)
