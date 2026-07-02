"""Tests for C1: rate-limit dependency + config-pull audit on GET /api/v1/config."""

from __future__ import annotations

import os

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

import tokensurf_server.ingest as ingest_module
from tokensurf_server import config as server_config
from tokensurf_server.app import create_app
from tokensurf_server.db import get_session
from tokensurf_server.models import AuditLog, Project, ProjectApiKey
from tokensurf_server.ratelimit import SlidingWindowLimiter
from tokensurf_server.secrets_service import set_secret
from tokensurf_server.security import generate_api_key, hash_key, key_prefix


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    server_config.get_settings.cache_clear()
    yield
    server_config.get_settings.cache_clear()


@pytest.fixture
def two_secret_setup(db_session: Session) -> Iterator[tuple]:
    """Project with two secrets; yields (client, project, raw_key)."""
    project = Project(id=new_id(), name="C1 Two-Secret Project", slug="c1-two-secret-proj")
    db_session.add(project)
    db_session.flush()

    raw_key = generate_api_key()
    db_session.add(
        ProjectApiKey(
            id=new_id(),
            project_id=project.id,
            key_hash=hash_key(raw_key),
            key_prefix=key_prefix(raw_key),
            label="c1-two-key",
        )
    )
    db_session.flush()

    for provider, plaintext in {
        "openai": "sk-openai-c1-secret",
        "anthropic": "sk-anth-c1-secret",
    }.items():
        set_secret(db_session, project_id=project.id, provider=provider, plaintext=plaintext)
    db_session.flush()

    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, project, raw_key
    app.dependency_overrides.clear()


@pytest.fixture
def rate_limit_setup(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    """Project with a monkeypatched limiter capped at 1 request per 60 s."""
    tiny_limiter = SlidingWindowLimiter(1, 60.0)
    monkeypatch.setattr(ingest_module, "_config_limiter", tiny_limiter)

    project = Project(id=new_id(), name="C1 Rate-Limit Project", slug="c1-rate-limit-proj")
    db_session.add(project)
    db_session.flush()

    raw_key = generate_api_key()
    db_session.add(
        ProjectApiKey(
            id=new_id(),
            project_id=project.id,
            key_hash=hash_key(raw_key),
            key_prefix=key_prefix(raw_key),
            label="c1-rl-key",
        )
    )
    db_session.flush()
    set_secret(db_session, project_id=project.id, provider="openai", plaintext="sk-rl-secret")
    db_session.flush()

    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, project, raw_key
    app.dependency_overrides.clear()


@pytest.fixture
def isolation_setup(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    """Two projects sharing a tiny limiter; yields (client, proj_a, key_a, proj_b, key_b)."""
    tiny_limiter = SlidingWindowLimiter(1, 60.0)
    monkeypatch.setattr(ingest_module, "_config_limiter", tiny_limiter)

    def _make_project(slug: str, secret: str) -> tuple[Project, str]:
        p = Project(id=new_id(), name=f"C1 Iso {slug}", slug=slug)
        db_session.add(p)
        db_session.flush()
        rk = generate_api_key()
        db_session.add(
            ProjectApiKey(
                id=new_id(),
                project_id=p.id,
                key_hash=hash_key(rk),
                key_prefix=key_prefix(rk),
                label=f"c1-iso-{slug}",
            )
        )
        db_session.flush()
        set_secret(db_session, project_id=p.id, provider="openai", plaintext=secret)
        db_session.flush()
        return p, rk

    project_a, raw_key_a = _make_project("c1-iso-proj-a", "sk-iso-a-secret")
    project_b, raw_key_b = _make_project("c1-iso-proj-b", "sk-iso-b-secret")

    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, project_a, raw_key_a, project_b, raw_key_b
    app.dependency_overrides.clear()


# ── tests ──────────────────────────────────────────────────────────────────────


def test_config_pull_returns_200_and_judge_keys(two_secret_setup: tuple) -> None:
    client, _project, raw_key = two_secret_setup
    resp = client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    data = resp.json()
    assert set(data["judge_keys"]) == {"openai", "anthropic"}


def test_config_pull_writes_exactly_one_audit_row(
    two_secret_setup: tuple, db_session: Session
) -> None:
    client, project, raw_key = two_secret_setup
    resp = client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200

    rows = db_session.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project.id,
            AuditLog.event == "config.pull",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].detail is not None
    assert rows[0].detail["key_count"] == 2


def test_config_pull_audit_detail_contains_no_secret_value(
    two_secret_setup: tuple, db_session: Session
) -> None:
    client, project, raw_key = two_secret_setup
    client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})

    rows = db_session.scalars(select(AuditLog).where(AuditLog.project_id == project.id)).all()
    for row in rows:
        detail_str = str(row.detail)
        assert "sk-openai-c1-secret" not in detail_str
        assert "sk-anth-c1-secret" not in detail_str


def test_config_pull_valid_usage_under_limit_succeeds(rate_limit_setup: tuple) -> None:
    client, _project, raw_key = rate_limit_setup
    # One call is within the limit of 1; must not be blocked.
    resp = client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200


def test_config_pull_rate_limit_blocks_after_limit_exceeded(rate_limit_setup: tuple) -> None:
    client, _project, raw_key = rate_limit_setup
    r1 = client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})
    assert r1.status_code == 200
    r2 = client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key}"})
    assert r2.status_code == 429
    assert "Retry-After" in r2.headers
    assert int(r2.headers["Retry-After"]) > 0


def test_config_pull_rate_limit_per_project_isolation(isolation_setup: tuple) -> None:
    client, _project_a, raw_key_a, _project_b, raw_key_b = isolation_setup
    # Exhaust project A's per-project quota (limit = 1).
    assert (
        client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key_a}"}).status_code
        == 200
    )
    assert (
        client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key_a}"}).status_code
        == 429
    )
    # Project B has its own per-project bucket and must be unaffected.
    assert (
        client.get("/api/v1/config", headers={"Authorization": f"Bearer {raw_key_b}"}).status_code
        == 200
    )
