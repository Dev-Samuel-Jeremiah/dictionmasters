"""
The secrets behind the offline app.

    Licence signing (Ed25519)
        The website signs each computer's licence; the app checks the
        signature with the PUBLIC key built into it, so a licence can't be
        written by hand or edited (more levels, a later end date) without
        the app noticing. Only the website holds the private key:
        DESKTOP_LICENCE_PRIVATE_KEY.

    Lesson encryption (AES-256-GCM)
        Every page, picture, recording and video in a release is encrypted.
        Each level has its own key, made from DESKTOP_CONTENT_KEY, and a
        computer is given the keys for its code's levels when it activates.
        So the installer can be copied freely: without a code it opens
        nothing, and a Level 1 code doesn't open Level 6.

Both settings default to values made from DJANGO_SECRET_KEY, which is fine
for trying things out. Before the first real installer, run
`manage.py desktop_keys`, put the two lines it prints in the server's .env,
and never change them: installed apps depend on them.

A sealed file ("blob"):

    b"DMB1" | piece size (4 bytes, big-endian) | pieces
    each piece = 12-byte nonce | ciphertext | 16-byte tag

Pieces are sealed one by one so the app can open the middle of a long
video (seeking) without decrypting all of it.
"""

import base64
import hashlib
import hmac
import json
import os
import struct

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

MAGIC = b"DMB1"
PIECE = 1024 * 1024
COMMON = "common"


def _derived(label):
    return hmac.new(settings.SECRET_KEY.encode(), f"dm-desktop:{label}".encode(), hashlib.sha256).digest()


def _setting_bytes(name):
    raw = (getattr(settings, name, "") or "").strip()
    return base64.b64decode(raw) if raw else b""


# ---------------------------------------------------------------- licences

def private_key():
    seed = _setting_bytes("DESKTOP_LICENCE_PRIVATE_KEY") or _derived("licence-signing")
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def public_key_b64():
    raw = private_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def sign(payload):
    """(licence, signature): the payload as base64 JSON, and its signature."""
    body = base64.b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
    signature = base64.b64encode(private_key().sign(body.encode())).decode()
    return body, signature


def verify(body, signature):
    """The payload of a licence this website signed, or None."""
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64()))
        public.verify(base64.b64decode(signature), str(body).encode())
        return json.loads(base64.b64decode(body))
    except Exception:            # bad base64, bad JSON, bad signature: all just "not ours"
        return None


def new_keys():
    """Two fresh lines for .env (manage.py desktop_keys)."""
    return {
        "DESKTOP_LICENCE_PRIVATE_KEY": base64.b64encode(os.urandom(32)).decode(),
        "DESKTOP_CONTENT_KEY": base64.b64encode(os.urandom(32)).decode(),
    }


# -------------------------------------------------------------- encryption

def content_key(group):
    """The key for one level's lessons ("Level 3"), or for the site's own
    styles and scripts that every level shares (COMMON)."""
    master = _setting_bytes("DESKTOP_CONTENT_KEY") or _derived("content")
    return hmac.new(master, f"group:{group}".encode(), hashlib.sha256).digest()


def content_key_b64(group):
    return base64.b64encode(content_key(group)).decode()


def blob_id(group, data):
    """A file's name in storage: the same file in the same group is stored
    once, and a release only uploads what's new."""
    return hashlib.sha256(group.encode() + b"\0" + data).hexdigest()[:40]


def seal(data, group):
    cipher = AESGCM(content_key(group))
    out = [MAGIC, struct.pack(">I", PIECE)]
    for start in range(0, max(len(data), 1), PIECE):
        nonce = os.urandom(12)
        out.append(nonce + cipher.encrypt(nonce, data[start:start + PIECE], None))
    return b"".join(out)


def unseal(blob, group):
    """The file a blob holds (for tests and checks; the app does this itself)."""
    assert blob[:4] == MAGIC, "not a sealed lesson file"
    (piece,) = struct.unpack(">I", blob[4:8])
    cipher = AESGCM(content_key(group))
    step = 12 + piece + 16
    data, offset = [], 8
    while offset < len(blob):
        chunk = blob[offset:offset + step]
        data.append(cipher.decrypt(chunk[:12], chunk[12:], None))
        offset += step
    return b"".join(data)
