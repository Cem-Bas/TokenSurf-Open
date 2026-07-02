"""Tests for web/csrf.py — CSRF double-submit token helpers."""

from __future__ import annotations

import os

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-csrf-secret-key!")

from collections.abc import Iterator

import pytest

from tokensurf_server import config as server_config


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    server_config.get_settings.cache_clear()
    yield
    server_config.get_settings.cache_clear()


def test_csrf_cookie_constant() -> None:
    from tokensurf_server.web.csrf import CSRF_COOKIE

    assert CSRF_COOKIE == "ts_csrf"


def test_issue_token_returns_nonempty_string() -> None:
    from tokensurf_server.web.csrf import issue_token

    token = issue_token()
    assert isinstance(token, str)
    assert len(token) > 0


def test_verify_round_trip() -> None:
    from tokensurf_server.web.csrf import issue_token, verify

    token = issue_token()
    assert verify(token, token) is True


def test_verify_missing_cookie_returns_false() -> None:
    from tokensurf_server.web.csrf import issue_token, verify

    token = issue_token()
    assert verify(None, token) is False


def test_verify_missing_form_token_returns_false() -> None:
    from tokensurf_server.web.csrf import issue_token, verify

    token = issue_token()
    assert verify(token, None) is False


def test_verify_both_none_returns_false() -> None:
    from tokensurf_server.web.csrf import verify

    assert verify(None, None) is False


def test_verify_tampered_cookie_returns_false() -> None:
    from tokensurf_server.web.csrf import issue_token, verify

    token = issue_token()
    tampered = token + "XXXINVALID"
    assert verify(tampered, token) is False


def test_verify_tampered_form_token_returns_false() -> None:
    from tokensurf_server.web.csrf import issue_token, verify

    token = issue_token()
    tampered = token + "XXXINVALID"
    assert verify(token, tampered) is False


def test_verify_two_separate_tokens_returns_false() -> None:
    """Two independently issued tokens encode different IDs and must not match."""
    from tokensurf_server.web.csrf import issue_token, verify

    token_a = issue_token()
    token_b = issue_token()
    # Two separate calls produce distinct tokens (each wraps a fresh new_id()).
    assert token_a != token_b
    assert verify(token_a, token_b) is False


def test_verify_invalid_signature_both_sides_returns_false() -> None:
    from tokensurf_server.web.csrf import verify

    assert verify("not.a.valid.token", "not.a.valid.token") is False
