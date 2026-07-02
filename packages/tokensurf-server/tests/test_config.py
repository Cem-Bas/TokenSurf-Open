import pytest
from pydantic import ValidationError


def test_settings_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/ts_test")
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    # Import inside the test so monkeypatch takes effect before module-level lru_cache runs.
    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.database_url == "postgresql+psycopg://user:pass@localhost:5432/ts_test"
    assert s.host == "0.0.0.0"
    assert s.port == 8000


def test_settings_respects_host_and_port_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")

    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.host == "127.0.0.1"
    assert s.port == 9000


def test_missing_database_url_raises_at_construction(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from tokensurf_server.config import Settings

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
