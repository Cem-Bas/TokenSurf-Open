from __future__ import annotations


def test_settings_has_session_secret_default(monkeypatch) -> None:
    """session_secret defaults to the dev placeholder with no env override."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.delenv("TOKENSURF_SESSION_SECRET", raising=False)

    from tokensurf_server.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]  # populated from env
    assert s.session_secret == "tokensurf-dev-secret-change-me"
    get_settings.cache_clear()


def test_settings_session_secret_env_override(monkeypatch) -> None:
    """TOKENSURF_SESSION_SECRET env var is picked up by Settings."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_SESSION_SECRET", "super-secret-for-test")

    from tokensurf_server.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]  # populated from env
    assert s.session_secret == "super-secret-for-test"
    get_settings.cache_clear()
