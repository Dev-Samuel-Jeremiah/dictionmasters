"""
Put an API key into .env without it ever being shown or pasted into a
shell history — and check it works before saving.

    python manage.py set_key OPENAI_API_KEY
    python manage.py set_key ELEVENLABS_API_KEY

The key is typed at a hidden prompt, tried against the service, and only
written if the service accepts it. A key pasted with its beginning cut
off — the usual cause of "Incorrect API key provided" — is caught here
rather than in the middle of a lesson.
"""

import getpass
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

CHECKS = {
    "OPENAI_API_KEY": {
        "url": "https://api.openai.com/v1/models",
        "headers": lambda key: {"Authorization": f"Bearer {key}"},
        "looks_right": lambda key: key.startswith("sk-"),
        "shape": 'an OpenAI key starts with "sk-" (usually "sk-proj-")',
        "service": "OpenAI",
    },
    "ELEVENLABS_API_KEY": {
        "url": "https://api.elevenlabs.io/v1/models",
        "headers": lambda key: {"xi-api-key": key},
        "looks_right": lambda key: key.startswith("sk_"),
        "shape": 'an ElevenLabs key starts with "sk_"',
        "service": "ElevenLabs",
    },
}


class Command(BaseCommand):
    help = "Set an API key in .env safely, checking it with the service first."

    def add_arguments(self, parser):
        parser.add_argument("name", help="The setting to write, e.g. OPENAI_API_KEY")
        parser.add_argument("--skip-check", action="store_true",
                            help="Write it without asking the service (for keys with limited permissions).")

    def handle(self, *args, **options):
        name = options["name"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9_]+", name):
            raise CommandError("That isn't a setting name.")
        env_path = Path(settings.BASE_DIR) / ".env"
        if not env_path.exists():
            raise CommandError(f"No .env at {env_path}.")

        key = getpass.getpass(f"Paste the value for {name} (it won't be shown): ").strip().strip('"').strip("'")
        if not key:
            raise CommandError("Nothing pasted — nothing changed.")
        if " " in key or "\n" in key:
            raise CommandError("That has a space or a line break in it, so it was pasted incompletely.")

        check = CHECKS.get(name)
        if check and not check["looks_right"](key):
            raise CommandError(
                f"That doesn't look whole: {check['shape']}, and what you pasted starts “{key[:4]}…”. "
                "Copy the key again from the very beginning."
            )
        if check and not options["skip_check"]:
            self.stdout.write(f"Asking {check['service']} whether the key works…")
            problem = _try_key(check, key)
            if problem:
                raise CommandError(f"{check['service']} refused it: {problem}. Nothing was changed.")
            self.stdout.write(self.style.SUCCESS(f"{check['service']} accepts it."))

        _write(env_path, name, key)
        self.stdout.write(self.style.SUCCESS(
            f"{name} saved in .env ({len(key)} characters, ending “{key[-4:]}”). "
            "Restart the server for it to take effect."
        ))


def _try_key(check, key):
    request = urllib.request.Request(check["url"], headers=check["headers"](key))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            json.load(response)
        return None
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            body = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(body)
                message = detail.get("error", {}).get("message") or detail.get("detail", {}).get("message") or ""
            except ValueError:
                message = ""
            # A key with limited permissions is still a real key.
            if "permission" in message.lower():
                return None
            return message.split(":")[0] or f"HTTP {error.code}"
        return f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return f"couldn't reach it ({error})"


def _write(env_path, name, key):
    """Replace that one line, leaving everything else exactly as it was."""
    lines = env_path.read_text().splitlines()
    written = False
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = f"{name}={key}"
            written = True
            break
    if not written:
        lines.append(f"{name}={key}")
    env_path.write_text("\n".join(lines).rstrip() + "\n")
