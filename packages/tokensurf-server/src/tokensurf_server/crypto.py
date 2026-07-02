"""Fernet-based symmetric encryption for channel secrets stored at rest.

The key is derived from TOKENSURF_SECRET_KEY via SHA-256 so any
arbitrary-length string can serve as the passphrase. Missing key always
raises SecretKeyMissing — secrets are never silently stored as plaintext.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from tokensurf_server.config import get_settings


class SecretKeyMissing(RuntimeError):
    """Raised when TOKENSURF_SECRET_KEY is required but not configured."""


def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        raise SecretKeyMissing(
            "TOKENSURF_SECRET_KEY is required to encrypt/decrypt channel secrets"
        )
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(plaintext: str) -> str:
    """Return a Fernet token (URL-safe base64 string) for *plaintext*."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decode and verify a Fernet *token*, returning the original plaintext."""
    return _fernet().decrypt(token.encode()).decode()
