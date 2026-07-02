"""Tests for the secret_key and SMTP configuration fields added in slice 2c (A1)."""

from __future__ import annotations


def test_secret_key_defaults_to_none(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    monkeypatch.delenv("TOKENSURF_SECRET_KEY", raising=False)

    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.secret_key is None


def test_secret_key_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "my-test-secret-key")

    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.secret_key == "my-test-secret-key"


def test_smtp_fields_default_to_none_except_port(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    for env_var in (
        "TOKENSURF_SMTP_HOST",
        "TOKENSURF_SMTP_PORT",
        "TOKENSURF_SMTP_USER",
        "TOKENSURF_SMTP_PASSWORD",
        "TOKENSURF_SMTP_FROM",
    ):
        monkeypatch.delenv(env_var, raising=False)

    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.smtp_host is None
    assert s.smtp_port == 587
    assert s.smtp_user is None
    assert s.smtp_password is None
    assert s.smtp_from is None


def test_smtp_fields_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db:5432/ts")
    monkeypatch.setenv("TOKENSURF_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("TOKENSURF_SMTP_PORT", "465")
    monkeypatch.setenv("TOKENSURF_SMTP_USER", "alerts@example.com")
    monkeypatch.setenv("TOKENSURF_SMTP_PASSWORD", "hunter2")
    monkeypatch.setenv("TOKENSURF_SMTP_FROM", "noreply@example.com")

    from tokensurf_server.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.smtp_host == "smtp.example.com"
    assert s.smtp_port == 465
    assert s.smtp_user == "alerts@example.com"
    assert s.smtp_password == "hunter2"
    assert s.smtp_from == "noreply@example.com"
