"""Startup validation (spec §8): a missing DATABASE_URL must fail loudly at boot."""

import pytest
from fastapi.testclient import TestClient


def test_startup_fails_without_database_url(monkeypatch):
    """Entering the app lifespan with no DATABASE_URL raises, rather than booting
    'healthy' and 500-ing on the first request."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from tokensurf_server.config import get_settings
    from tokensurf_server.db import get_engine

    # Clear cached singletons so the missing env var is actually re-read.
    get_settings.cache_clear()
    get_engine.cache_clear()

    from tokensurf_server.app import create_app

    app = create_app()
    with pytest.raises(Exception):  # noqa: B017 — Starlette wraps the ValidationError on startup
        with TestClient(app):
            pass

    # Restore caches so later tests (which rely on the env-provided URL) are clean.
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_startup_succeeds_with_database_url(db_session):
    """With DATABASE_URL present (the test default), startup completes and the
    app serves /healthz."""
    from tokensurf_server.app import create_app
    from tokensurf_server.db import get_session

    def _override_session():
        yield db_session

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
    app.dependency_overrides.clear()
