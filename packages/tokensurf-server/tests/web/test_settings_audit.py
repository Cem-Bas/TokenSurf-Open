"""Tests for Group D3: settings_detail middleware CSRF handoff, audit rows on secret
create/delete, Recent Activity rendering, and no secret values in audit detail."""

from __future__ import annotations

import os
import re

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server import config as server_config
from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import AuditLog, Project, Run, User
from tokensurf_server.security import hash_password


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    server_config.get_settings.cache_clear()
    yield
    server_config.get_settings.cache_clear()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, follow_redirects=False, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def seeded(db_session: Session) -> dict:
    proj = Project(id=new_id(), name="Audit Project", slug="audit-proj-" + new_id()[:6])
    db_session.add(proj)
    run = Run(
        id=new_id(),
        project_id=proj.id,
        label="v1",
        status="completed",
        n_cases=1,
        pass_rate=1.0,
        mean_score=None,
        error_count=0,
    )
    db_session.add(run)
    user = User(
        id=new_id(),
        email="audit-user@example.test",
        password_hash=hash_password("pass9999"),
    )
    db_session.add(user)
    db_session.flush()
    return {"proj": proj, "run": run, "user": user}


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(client: TestClient) -> str:
    resp = client.post(
        "/login",
        data={
            "email": "audit-user@example.test",
            "password": "pass9999",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return resp.cookies["ts_session"]


def _get_settings_csrf_token(client: TestClient, session_cookie: str, slug: str) -> str:
    """GET /settings/{slug} and extract the csrf_token hidden-field value."""
    resp = client.get(f"/settings/{slug}", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    assert m is not None, "csrf_token hidden field not found in settings page"
    return m.group(1)


# ---------------------------------------------------------------------------
# Recent Activity section rendering
# ---------------------------------------------------------------------------


def test_settings_page_renders_recent_activity_heading(client: TestClient, seeded: dict) -> None:
    """GET /settings/{slug} must include a 'Recent Activity' section heading."""
    session_cookie = _login(client)
    resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    assert "Recent Activity" in resp.text


def test_settings_page_shows_no_recent_activity_line_when_empty(
    client: TestClient, seeded: dict
) -> None:
    """When the audit log is empty the settings page must show the empty-state line."""
    session_cookie = _login(client)
    resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    assert "No recent activity." in resp.text


# ---------------------------------------------------------------------------
# secret.set audit row
# ---------------------------------------------------------------------------


def test_create_secret_writes_secret_set_audit_row(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    """POST /settings/{slug}/secrets must write one secret.set audit row with provider in detail."""
    session_cookie = _login(client)
    csrf_token = _get_settings_csrf_token(client, session_cookie, seeded["proj"].slug)

    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": "sk-test-audit", "csrf_token": csrf_token},
        cookies={"ts_session": session_cookie},
    )
    assert resp.status_code == 303

    rows = (
        db_session.execute(
            select(AuditLog).where(
                AuditLog.project_id == seeded["proj"].id,
                AuditLog.event == "secret.set",
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].detail == {"provider": "openai"}
    assert rows[0].actor == f"user:{seeded['user'].email}"


def test_create_secret_audit_row_never_contains_plaintext_secret(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    """The secret.set audit row detail must never contain the plaintext secret value."""
    plaintext = "sk-ultra-secret-must-not-appear-in-audit-detail"
    session_cookie = _login(client)
    csrf_token = _get_settings_csrf_token(client, session_cookie, seeded["proj"].slug)

    client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "anthropic", "secret": plaintext, "csrf_token": csrf_token},
        cookies={"ts_session": session_cookie},
    )

    rows = (
        db_session.execute(select(AuditLog).where(AuditLog.project_id == seeded["proj"].id))
        .scalars()
        .all()
    )
    assert rows, "Expected at least one audit row"
    for row in rows:
        detail_str = str(row.detail) if row.detail else ""
        assert plaintext not in detail_str, "Secret value must never appear in audit_logs.detail"


# ---------------------------------------------------------------------------
# secret.delete audit row
# ---------------------------------------------------------------------------


def test_delete_secret_writes_secret_delete_audit_row(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    """POST /settings/{slug}/secrets/{provider}/delete must write a secret.delete audit row."""
    from tokensurf_server.crypto import encrypt
    from tokensurf_server.models import ProjectSecret

    db_session.add(
        ProjectSecret(
            id=new_id(),
            project_id=seeded["proj"].id,
            provider="gemini",
            key_enc=encrypt("sk-to-delete"),
        )
    )
    db_session.flush()

    session_cookie = _login(client)
    csrf_token = _get_settings_csrf_token(client, session_cookie, seeded["proj"].slug)

    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets/gemini/delete",
        data={"csrf_token": csrf_token},
        cookies={"ts_session": session_cookie},
    )
    assert resp.status_code == 303

    rows = (
        db_session.execute(
            select(AuditLog).where(
                AuditLog.project_id == seeded["proj"].id,
                AuditLog.event == "secret.delete",
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].detail == {"provider": "gemini"}
    assert rows[0].actor == f"user:{seeded['user'].email}"


# ---------------------------------------------------------------------------
# Recent Activity renders audit rows + secret value never in HTML
# ---------------------------------------------------------------------------


def test_settings_page_lists_secret_set_event_after_create(
    client: TestClient, seeded: dict
) -> None:
    """After a secret.set the settings page must list the event in Recent Activity."""
    session_cookie = _login(client)
    csrf_token = _get_settings_csrf_token(client, session_cookie, seeded["proj"].slug)

    client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": "sk-render-test", "csrf_token": csrf_token},
        cookies={"ts_session": session_cookie},
    )

    resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    assert "secret.set" in resp.text
    assert "sk-render-test" not in resp.text


# ---------------------------------------------------------------------------
# Existing settings CSRF flow still works after middleware handoff
# ---------------------------------------------------------------------------


def test_settings_csrf_still_works_after_middleware_handoff(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    """GET /settings/{slug} -> extract token -> POST secret still succeeds (middleware owns cookie)."""  # noqa: E501
    session_cookie = _login(client)
    csrf_token = _get_settings_csrf_token(client, session_cookie, seeded["proj"].slug)

    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": "sk-handoff-check", "csrf_token": csrf_token},
        cookies={"ts_session": session_cookie},
    )
    assert resp.status_code == 303

    resp_missing = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": "sk-no-csrf"},
        cookies={"ts_session": session_cookie},
    )
    assert resp_missing.status_code == 403
