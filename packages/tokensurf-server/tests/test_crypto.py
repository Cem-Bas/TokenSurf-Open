"""Tests for the Fernet-based crypto module (slice 2c A2).

Each test monkeypatches TOKENSURF_SECRET_KEY and explicitly clears the
lru_cache on get_settings so crypto.py picks up the patched value.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear lru_cache before and after every test in this module."""
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "test-secret-key")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.crypto import decrypt, encrypt

    plaintext = "https://hooks.slack.com/services/T000/B000/xoxb-secret"
    ciphertext = encrypt(plaintext)
    assert decrypt(ciphertext) == plaintext


def test_ciphertext_differs_from_plaintext(monkeypatch):
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "test-secret-key")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.crypto import encrypt

    plaintext = "https://hooks.example.com/webhook/secret"
    assert encrypt(plaintext) != plaintext


def test_missing_key_raises_secret_key_missing(monkeypatch):
    monkeypatch.delenv("TOKENSURF_SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.crypto import SecretKeyMissing, encrypt

    with pytest.raises(SecretKeyMissing, match="TOKENSURF_SECRET_KEY"):
        encrypt("any-value")


def test_wrong_key_raises_invalid_token(monkeypatch):
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "first-key-aaa")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.crypto import encrypt

    ciphertext = encrypt("my-webhook-secret")

    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "second-different-key-bbb")
    get_settings.cache_clear()

    from tokensurf_server.crypto import decrypt

    with pytest.raises(InvalidToken):
        decrypt(ciphertext)
