"""Tests for judge-key Settings CRUD routes added in Slice 2d."""

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
from tokensurf_server.crypto import decrypt, encrypt
from tokensurf_server.db import get_session
from tokensurf_server.models import Project, ProjectSecret, Run, User
from tokensurf_server.security import hash_password
from tokensurf_server.web.csrf import CSRF_COOKIE


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
    """Seed one project, one run, and one user."""
    proj = Project(id=new_id(), name="Secrets Project", slug="secrets-proj-" + new_id()[:6])
    db_session.add(proj)
    run = Run(
        id=new_id(),
        project_id=proj.id,
        label="v1",
        status="completed",
        n_cases=2,
        pass_rate=0.5,
        mean_score=None,
        error_count=0,
    )
    db_session.add(run)
    user = User(
        id=new_id(),
        email="admin@secrets.test",
        password_hash=hash_password("pass1234"),
    )
    db_session.add(user)
    db_session.flush()
    return {"proj": proj, "run": run, "user": user}


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(
    client: TestClient,
    email: str = "admin@secrets.test",
    password: str = "pass1234",
) -> str:
    resp = client.post(
        "/login", data={"email": email, "password": password, "csrf_token": _csrf(client)}
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return resp.cookies["ts_session"]


def _csrf_from_page(resp_text: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp_text)
    assert m is not None, "csrf_token hidden field not found in HTML"
    return m.group(1)


# ---------------------------------------------------------------------------
# GET /settings/{slug} — secrets list rendered in context
# BINDING CORRECTION #2: Only assert route behavior (status 200) and
# that plaintext is never rendered. HTML rendering assertions ("openai",
# "•••• set") belong in C3 after the template renders the section.
# ---------------------------------------------------------------------------


def test_settings_detail_plaintext_never_in_html(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    db_session.add(
        ProjectSecret(
            id=new_id(),
            project_id=seeded["proj"].id,
            provider="openai",
            key_enc=encrypt("sk-secret"),
        )
    )
    db_session.flush()

    cookie = _login(client)
    resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "sk-secret" not in resp.text, "Plaintext secret must never appear in HTML"


# ---------------------------------------------------------------------------
# POST /settings/{slug}/secrets — add / upsert
# ---------------------------------------------------------------------------


def test_create_secret_missing_csrf_returns_403(client: TestClient, seeded: dict) -> None:
    cookie = _login(client)
    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": "sk-no-csrf"},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_create_secret_bad_csrf_returns_403(client: TestClient, seeded: dict) -> None:
    cookie = _login(client)
    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={
            "provider": "openai",
            "secret": "sk-bad-csrf",
            "csrf_token": "tampered.invalid",
        },
        cookies={"ts_session": cookie, CSRF_COOKIE: "also.wrong"},
    )
    assert resp.status_code == 403


def test_create_secret_valid_csrf_stores_encrypted_and_redirects(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    cookie = _login(client)
    get_resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    plaintext = "sk-openai-test-value"
    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets",
        data={"provider": "openai", "secret": plaintext, "csrf_token": csrf_token},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"/settings/{seeded['proj'].slug}")

    rows = (
        db_session.execute(
            select(ProjectSecret).where(ProjectSecret.project_id == seeded["proj"].id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].key_enc != plaintext
    assert decrypt(rows[0].key_enc) == plaintext


def test_create_secret_upserts_on_duplicate_provider(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    cookie = _login(client)

    for value in ["sk-first", "sk-second"]:
        get_resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": cookie})
        csrf_token = _csrf_from_page(get_resp.text)
        client.post(
            f"/settings/{seeded['proj'].slug}/secrets",
            data={"provider": "anthropic", "secret": value, "csrf_token": csrf_token},
            cookies={"ts_session": cookie},
        )

    rows = (
        db_session.execute(
            select(ProjectSecret).where(
                ProjectSecret.project_id == seeded["proj"].id,
                ProjectSecret.provider == "anthropic",
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "Upsert must not create a duplicate row"
    assert decrypt(rows[0].key_enc) == "sk-second"


def test_create_secret_value_never_in_html(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    plaintext = "ultra-secret-judge-key-do-not-render"
    db_session.add(
        ProjectSecret(
            id=new_id(),
            project_id=seeded["proj"].id,
            provider="gemini",
            key_enc=encrypt(plaintext),
        )
    )
    db_session.flush()

    cookie = _login(client)
    resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert plaintext not in resp.text, "Plaintext must never appear in rendered HTML"


# ---------------------------------------------------------------------------
# POST /settings/{slug}/secrets/{provider}/delete
# ---------------------------------------------------------------------------


def test_delete_secret_missing_csrf_returns_403(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    db_session.add(
        ProjectSecret(
            id=new_id(),
            project_id=seeded["proj"].id,
            provider="openai",
            key_enc=encrypt("sk-to-delete"),
        )
    )
    db_session.flush()

    cookie = _login(client)
    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets/openai/delete",
        data={},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_delete_secret_valid_csrf_removes_row_and_redirects(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    secret_row = ProjectSecret(
        id=new_id(),
        project_id=seeded["proj"].id,
        provider="openai",
        key_enc=encrypt("sk-to-delete"),
    )
    db_session.add(secret_row)
    db_session.flush()

    cookie = _login(client)
    get_resp = client.get(f"/settings/{seeded['proj'].slug}", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    resp = client.post(
        f"/settings/{seeded['proj'].slug}/secrets/openai/delete",
        data={"csrf_token": csrf_token},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"/settings/{seeded['proj'].slug}")

    remaining = db_session.execute(
        select(ProjectSecret).where(ProjectSecret.id == secret_row.id)
    ).scalar_one_or_none()
    assert remaining is None
