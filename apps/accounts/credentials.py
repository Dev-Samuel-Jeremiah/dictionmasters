"""Encryption helpers for downloadable school login sheets.

The authentication password in the user table is always a one-way Django
hash. This module handles the separate encrypted copy used only when staff
download school credentials.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet():
    key = getattr(settings, "SCHOOL_CREDENTIALS_ENCRYPTION_KEY", "")
    if not key:
        return None
    if isinstance(key, str):
        key = key.encode("ascii")
    return Fernet(key)


def encrypt_login_password(password):
    """Encrypt a school account password, or return empty if no key is set."""
    fernet = _fernet()
    if fernet is None or password is None:
        return ""
    return fernet.encrypt(str(password).encode("utf-8")).decode("ascii")


def decrypt_login_password(ciphertext):
    """Return a saved password, or None if it was never stored or can't decrypt."""
    if not ciphertext:
        return None
    fernet = _fernet()
    if fernet is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError):
        return None
