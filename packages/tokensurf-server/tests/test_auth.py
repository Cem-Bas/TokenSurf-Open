from __future__ import annotations


def test_make_session_returns_non_empty_string(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "test-secret-key")

    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.auth import make_session

    token = make_session("user-id-abc123")
    assert isinstance(token, str)
    assert len(token) > 10
    get_settings.cache_clear()


def test_read_session_round_trip(monkeypatch) -> None:
    """make_session then read_session recovers the original user_id."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "test-secret-key")

    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.auth import make_session, read_session

    uid = "user-id-abc123"
    assert read_session(make_session(uid)) == uid
    get_settings.cache_clear()


def test_read_session_none_input_returns_none(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "test-secret-key")

    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.auth import read_session

    assert read_session(None) is None
    get_settings.cache_clear()


def test_read_session_tampered_token_returns_none(monkeypatch) -> None:
    """A token with bytes corrupted in the middle is rejected."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "test-secret-key")

    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.auth import make_session, read_session

    token = make_session("user-id-abc123")
    mid = len(token) // 2
    tampered = token[:mid] + "~~~~" + token[mid:]
    assert read_session(tampered) is None
    get_settings.cache_clear()


def test_read_session_alien_secret_returns_none(monkeypatch) -> None:
    """A token signed with a different secret is rejected."""
    from itsdangerous import URLSafeSerializer

    # Create a token outside of auth.make_session so we control the secret.
    alien_token = URLSafeSerializer("alien-secret", salt="ts-session").dumps("user-id-abc123")

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "test-secret-key")

    from tokensurf_server.config import get_settings

    get_settings.cache_clear()

    from tokensurf_server.auth import read_session

    assert read_session(alien_token) is None
    get_settings.cache_clear()
