"""
Unlocking a computer with no internet at all (the offline app's codes).

A school installs a level from a flash drive. The app shows the computer's
number (from the computer's own id); the school sends it to Diction Masters,
who makes that computer's unlock code in /admin/ ("Unlock a computer"); the
school types it in. Nothing ever goes online.

How it holds together with no secret inside the app:

    factor(level)   8 bytes made from DESKTOP_CONTENT_KEY. It's what opens a
                    level's lesson keys, and it is NOT in the installer.
    wrap(level)     the level's lesson keys (and the shared styles' key),
                    locked with that level's factor. This IS in the installer
                    (the release's manifest), useless on its own.
    the code        carries the factor, scrambled with a mask made from the
                    computer's number, the level and the end date. The app
                    unscrambles it with this computer's number: on another
                    computer, for another level or with the end date changed,
                    it gets a wrong factor, and the lessons don't open.

So a flash drive with no code opens nothing, a code works on one computer
only, and its end date can't be edited. Honestly: someone who has a working
code AND takes the app apart could recover that level's factor; that's the
limit of anything that works fully offline.

    Computer number   7 characters of the id's hash and a check character,
                      shown as XXXX-XXXX.
    Unlock code       95 bits as 20 characters, DM-XXXX-XXXX-XXXX-XXXX-XXXX:
                      version (2 bits) | level (4) | end date (13: days from
                      EPOCH, 0 = none) | scrambled factor (64) | check (12),
                      the check catching typing mistakes before anything else.

The app does the same sums (dictionmasters-desktop, src/main/unlock.js).
Change both together, and never change LEVELS' order or EPOCH.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apps.echospell.models import LEVEL_NAME_CHOICES

from . import keys
from .models import CODE_ALPHABET

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]      # a level's number in codes: its place here
EPOCH = datetime.date(2026, 1, 1)
VERSION = 1
BASE = len(CODE_ALPHABET)
COMPUTER_CHARS = 7
CODE_CHARS = 20


def _chars(number, length):
    out = []
    for _ in range(length):
        number, digit = divmod(number, BASE)
        out.append(CODE_ALPHABET[digit])
    return "".join(reversed(out))


def _number(text):
    value = 0
    for char in text:
        value = value * BASE + CODE_ALPHABET.index(char)
    return value


def _letters(raw):
    return "".join(char for char in str(raw or "").upper() if char.isalnum())


def _check_char(data):
    return CODE_ALPHABET[sum((place + 1) * CODE_ALPHABET.index(char) for place, char in enumerate(data)) % BASE]


# ------------------------------------------------------------ the computer

def computer_number(machine_id):
    """The number a computer shows, from its own id (the app does this)."""
    digest = hashlib.sha256(b"dm-computer|" + str(machine_id).strip().lower().encode()).digest()
    data = _chars(int.from_bytes(digest[:6], "big") % BASE ** COMPUTER_CHARS, COMPUTER_CHARS)
    return data + _check_char(data)


def clean_computer(raw):
    """A computer number as typed (any case, with or without the dash), or
    "" if it isn't one: a wrong or missing character is caught here."""
    letters = _letters(raw)
    if len(letters) != COMPUTER_CHARS + 1 or any(char not in CODE_ALPHABET for char in letters):
        return ""
    return letters if _check_char(letters[:-1]) == letters[-1] else ""


def show_computer(number):
    return f"{number[:4]}-{number[4:]}" if number else ""


# ---------------------------------------------------------------- the keys

def factor(level):
    master = keys._setting_bytes("DESKTOP_CONTENT_KEY") or keys._derived("content")
    return hmac.new(master, f"unlock-factor:{level}".encode(), hashlib.sha256).digest()[:8]


def _unwrap_key(level_factor):
    return hashlib.sha256(b"dm-unwrap|" + level_factor).digest()


def wrap(level):
    """The level's lesson keys, locked with its factor: goes in the release."""
    plain = json.dumps({level: keys.content_key_b64(level), keys.COMMON: keys.content_key_b64(keys.COMMON)}).encode()
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_unwrap_key(factor(level))).encrypt(nonce, plain, level.encode())).decode()


def unwrap(wrapped, level, level_factor):
    """The keys a wrap holds (for tests; the app does this), or None."""
    try:
        raw = base64.b64decode(wrapped)
        return json.loads(AESGCM(_unwrap_key(level_factor)).decrypt(raw[:12], raw[12:], level.encode()))
    except Exception:
        return None


# --------------------------------------------------------------- the codes

def _mask(computer, level_index, days):
    digest = hashlib.sha256(f"dm-unlock|{VERSION}|{computer}|{level_index}|{days}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _check(value):
    return int.from_bytes(hashlib.sha256(b"dm-check|" + value.to_bytes(11, "big")).digest()[:2], "big") >> 4


def _days(until):
    if not until:
        return 0
    days = (until - EPOCH).days
    if not 1 <= days < 8192:
        raise ValueError("The end date must be between 2 January 2026 and 2048.")
    return days


def make_code(computer, level, until=None):
    """The unlock code for this computer, level and end date (or none)."""
    computer = clean_computer(computer)
    if not computer:
        raise ValueError("That isn't a computer number: check each character.")
    index = LEVELS.index(level)
    days = _days(until)
    masked = int.from_bytes(factor(level), "big") ^ _mask(computer, index, days)
    value = (((VERSION << 4 | index) << 13 | days) << 64) | masked
    letters = _chars(value << 12 | _check(value), CODE_CHARS)
    return "DM-" + "-".join(letters[i:i + 4] for i in range(0, CODE_CHARS, 4))


def read_code(code, computer):
    """{level, until} if this is a right code for this computer, else None."""
    letters = _letters(code)
    if letters.startswith("DM") and len(letters) == CODE_CHARS + 2:
        letters = letters[2:]
    computer = clean_computer(computer)
    if len(letters) != CODE_CHARS or not computer or any(char not in CODE_ALPHABET for char in letters):
        return None
    full = _number(letters)
    value, check = full >> 12, full & 0xFFF
    if value >= 1 << 83 or _check(value) != check:
        return None
    masked = value & ((1 << 64) - 1)
    days = (value >> 64) & 0x1FFF
    index = (value >> 77) & 0xF
    if value >> 81 != VERSION or index >= len(LEVELS):
        return None
    level = LEVELS[index]
    if masked ^ _mask(computer, index, days) != int.from_bytes(factor(level), "big"):
        return None
    return {"level": level, "until": EPOCH + datetime.timedelta(days=days) if days else None}
