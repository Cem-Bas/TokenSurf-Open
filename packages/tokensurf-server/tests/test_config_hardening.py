"""Tests for config.py hardening — INSECURE_SESSION_SECRET_DEFAULT,
MIN_SESSION_SECRET_LEN constants and config_rate_limit field.
"""

from __future__ import annotations


def test_insecure_session_secret_default_constant_exists() -> None:
    from tokensurf_server.config import INSECURE_SESSION_SECRET_DEFAULT

    assert INSECURE_SESSION_SECRET_DEFAULT == "tokensurf-dev-secret-change-me"


def test_min_session_secret_len_constant_exists() -> None:
    from tokensurf_server.config import MIN_SESSION_SECRET_LEN

    assert MIN_SESSION_SECRET_LEN == 32


def test_session_secret_default_equals_constant(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.delenv("TOKENSURF_SESSION_SECRET", raising=False)

    from tokensurf_server.config import INSECURE_SESSION_SECRET_DEFAULT, Settings, get_settings

    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]
    assert s.session_secret == INSECURE_SESSION_SECRET_DEFAULT
    get_settings.cache_clear()


def test_config_rate_limit_default(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.delenv("TOKENSURF_CONFIG_RATE_LIMIT", raising=False)

    from tokensurf_server.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]
    assert s.config_rate_limit == "30/60"
    get_settings.cache_clear()


def test_config_rate_limit_env_override(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
    )
    monkeypatch.setenv("TOKENSURF_CONFIG_RATE_LIMIT", "5/30")

    from tokensurf_server.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings()  # type: ignore[call-arg]
    assert s.config_rate_limit == "5/30"
    get_settings.cache_clear()
