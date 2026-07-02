# tests/test_integration_e2e_judge_keys.py
"""Full end-to-end integration test: judge keys.

Flow verified in one suite:
1. Seed project + ingest key + user via db_session (rolled back after test —
   uses the conftest savepoint pattern so no residue survives).
2. Set TOKENSURF_SECRET_KEY so crypto.encrypt/decrypt works.
3. Log in via the dashboard.
4. GET /settings/{slug} — obtain CSRF cookie + token.
5. POST /settings/{slug}/secrets — set openai key via the Settings form; expect 303.
6. Assert the key_enc row is ciphertext, never plaintext.
7. GET /api/v1/config with the project ingest bearer key — assert decrypted value returned.
8. Assert bad/missing bearer -> 401.
9. Assert project-with-no-secrets config returns {"judge_keys": {}}.
10. GET /settings/{slug} — assert the plaintext key NEVER appears in the HTML.
11. GET /api/v1/config with caplog at DEBUG — assert plaintext never appears in any log record.
12. Upsert: re-POST the same provider; assert only one DB row, config returns updated value.
13. Delete: POST /settings/{slug}/secrets/{provider}/delete; assert config returns empty.
14. Missing CSRF on secrets POST -> 403.

All DB state rolls back after each test; no _clean_db_rows fixture needed here.
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.db import get_session
from tokensurf_server.models import Project, ProjectApiKey, User
from tokensurf_server.security import generate_api_key, hash_key, hash_password, key_prefix
from tokensurf_server.web.csrf import CSRF_COOKIE

_SECRET_KEY = "test-e2e-judge-key-32bytes!!!!"
_OPENAI_PLAINTEXT = "sk-test-openai-abcdef123456"
_ANTHROPIC_PLAINTEXT = "sk-ant-test-anthropic-789xyz"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_secret_key(monkeypatch):
    """Set TOKENSURF_SECRET_KEY so encrypt/decrypt works; clear settings cache."""
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", _SECRET_KEY)
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(db_session: Session):
    """Fresh app with get_session overridden to the per-test rolled-back session."""
    from tokensurf_server.app import create_app

    _app = create_app()

    def _override():
        yield db_session

    _app.dependency_overrides[get_session] = _override
    with TestClient(_app, follow_redirects=False, raise_server_exceptions=True) as c:
        yield c
    _app.dependency_overrides.clear()


@pytest.fixture
def seeded(db_session: Session):
    """Seed one project, one ingest API key, and one dashboard user."""
    slug = "jk-proj-" + new_id()[:6]
    proj = Project(id=new_id(), name="Judge Key Project", slug=slug)
    db_session.add(proj)

    raw_key = generate_api_key()
    pak = ProjectApiKey(
        id=new_id(),
        project_id=proj.id,
        key_hash=hash_key(raw_key),
        key_prefix=key_prefix(raw_key),
        label="jk-key",
    )
    db_session.add(pak)

    user = User(
        id=new_id(),
        email=f"jk-{new_id()[:6]}@example.com",
        password_hash=hash_password("jk-pass"),
    )
    db_session.add(user)
    db_session.flush()

    return {"proj": proj, "raw_key": raw_key, "user": user}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(client: TestClient, email: str, password: str) -> str:
    resp = client.post(
        "/login", data={"email": email, "password": password, "csrf_token": _csrf(client)}
    )
    assert resp.status_code == 303, f"login failed: {resp.status_code} {resp.text[:200]}"
    return resp.cookies["ts_session"]


def _get_csrf(client: TestClient, slug: str, auth: dict) -> str:
    """GET /settings/{slug}, return (session_cookie_val, csrf_token)."""
    resp = client.get(f"/settings/{slug}", cookies=auth)
    assert resp.status_code == 200, resp.text[:400]
    token = resp.cookies[CSRF_COOKIE]
    assert token
    return token


# ---------------------------------------------------------------------------
# Main end-to-end test
# ---------------------------------------------------------------------------


def test_judge_key_full_flow_settings_form_to_config_pull(
    db_session: Session,
    client: TestClient,
    seeded: dict,
    caplog,
) -> None:
    """End-to-end: Settings form -> encrypted storage -> config pull -> no plaintext in logs."""
    from tokensurf_server.models import ProjectSecret

    proj = seeded["proj"]
    slug = proj.slug
    raw_key = seeded["raw_key"]
    user_email = seeded["user"].email

    # ── 1. Login ─────────────────────────────────────────────────────────────
    session_cookie = _login(client, user_email, "jk-pass")
    auth = {"ts_session": session_cookie}

    # ── 2. GET /settings/{slug} — obtain CSRF token ──────────────────────────
    csrf_token = _get_csrf(client, slug, auth)
    secret_cookies = {**auth, CSRF_COOKIE: csrf_token}

    # ── 3. POST /settings/{slug}/secrets — set openai key via the form ───────
    post_resp = client.post(
        f"/settings/{slug}/secrets",
        data={
            "provider": "openai",
            "secret": _OPENAI_PLAINTEXT,
            "csrf_token": csrf_token,
        },
        cookies=secret_cookies,
    )
    assert post_resp.status_code == 303, (
        f"Expected 303 after secret creation, got {post_resp.status_code}: {post_resp.text[:300]}"
    )
    assert post_resp.headers["location"].endswith(f"/settings/{slug}")

    # ── 4. Verify the key_enc row is ciphertext, not plaintext ───────────────
    secret_row = db_session.scalar(
        select(ProjectSecret).where(
            ProjectSecret.project_id == proj.id,
            ProjectSecret.provider == "openai",
        )
    )
    assert secret_row is not None, "ProjectSecret row must be committed after Settings POST"
    assert secret_row.key_enc != _OPENAI_PLAINTEXT, (
        "key_enc must be ciphertext, never the plaintext value"
    )
    assert _OPENAI_PLAINTEXT not in secret_row.key_enc, (
        "plaintext must not appear anywhere inside key_enc"
    )

    # ── 5. GET /api/v1/config — returns decrypted judge key ──────────────────
    config_resp = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert config_resp.status_code == 200, (
        f"GET /api/v1/config must return 200; got {config_resp.status_code}: "
        f"{config_resp.text[:300]}"
    )
    body = config_resp.json()
    assert "judge_keys" in body, "Response body must contain the 'judge_keys' key"
    assert body["judge_keys"].get("openai") == _OPENAI_PLAINTEXT, (
        f"judge_keys.openai must equal the original plaintext; "
        f"got {body['judge_keys'].get('openai')!r}"
    )
    # Security: config endpoint must set Cache-Control: no-store
    cache_header = config_resp.headers.get("cache-control", "")
    assert "no-store" in cache_header, (
        f"GET /api/v1/config must return Cache-Control: no-store; got {cache_header!r}"
    )

    # ── 6. Bad bearer -> 401; missing bearer -> 401 ──────────────────────────
    bad_resp = client.get(
        "/api/v1/config",
        headers={"Authorization": "Bearer tsk_badbadbadbadbadbadbadbad"},
    )
    assert bad_resp.status_code == 401, f"Bad bearer must return 401; got {bad_resp.status_code}"
    no_auth_resp = client.get("/api/v1/config")
    assert no_auth_resp.status_code == 401, (
        f"Missing bearer must return 401; got {no_auth_resp.status_code}"
    )

    # ── 7. GET /settings/{slug} — plaintext NEVER appears in the HTML ─────────
    settings_resp = client.get(f"/settings/{slug}", cookies=auth)
    assert settings_resp.status_code == 200
    settings_html = settings_resp.text
    assert _OPENAI_PLAINTEXT not in settings_html, (
        "Plaintext judge key must NEVER appear in the Settings page HTML"
    )
    assert secret_row.key_enc not in settings_html, (
        "Ciphertext (key_enc) must NEVER appear in the Settings page HTML"
    )
    # The provider name and the "set" indicator must be visible
    assert "openai" in settings_html, "Settings page must list 'openai' as a configured provider"

    # ── 8. caplog: plaintext must not appear in any log during config pull ────
    with caplog.at_level(logging.DEBUG):
        log_resp = client.get(
            "/api/v1/config",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert log_resp.status_code == 200
    for record in caplog.records:
        msg = record.getMessage()
        assert _OPENAI_PLAINTEXT not in msg, f"Plaintext key leaked into log record: {msg!r}"
    assert _OPENAI_PLAINTEXT not in caplog.text, (
        "Plaintext key must never appear in any captured log output"
    )


# ---------------------------------------------------------------------------
# Ancillary integration assertions
# ---------------------------------------------------------------------------


def test_config_endpoint_returns_empty_for_project_with_no_secrets(
    db_session: Session,
    client: TestClient,
    seeded: dict,
) -> None:
    """A project with no secrets configured returns {"judge_keys": {}}."""
    raw_key = seeded["raw_key"]
    resp = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"judge_keys": {}}


def test_settings_form_upserts_on_duplicate_provider(
    db_session: Session,
    client: TestClient,
    seeded: dict,
) -> None:
    """Re-posting the same provider upserts; no duplicate rows; config returns updated value."""
    from tokensurf_server.models import ProjectSecret

    proj = seeded["proj"]
    slug = proj.slug
    raw_key = seeded["raw_key"]
    user_email = seeded["user"].email

    session_cookie = _login(client, user_email, "jk-pass")
    auth = {"ts_session": session_cookie}

    # First POST: set openai to "sk-original"
    csrf1 = _get_csrf(client, slug, auth)
    client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "openai", "secret": "sk-original", "csrf_token": csrf1},
        cookies={**auth, CSRF_COOKIE: csrf1},
    )

    # Second POST: overwrite openai with "sk-updated"
    csrf2 = _get_csrf(client, slug, auth)
    resp2 = client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "openai", "secret": "sk-updated", "csrf_token": csrf2},
        cookies={**auth, CSRF_COOKIE: csrf2},
    )
    assert resp2.status_code == 303

    # Exactly ONE row for (project_id, provider=openai)
    count = db_session.scalar(
        select(func.count(ProjectSecret.id)).where(
            ProjectSecret.project_id == proj.id,
            ProjectSecret.provider == "openai",
        )
    )
    assert count == 1, "Upsert must not create a second row for the same (project, provider)"

    # Config returns the updated value
    config_resp = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert config_resp.json()["judge_keys"]["openai"] == "sk-updated"


def test_settings_form_missing_csrf_returns_403(
    client: TestClient,
    seeded: dict,
) -> None:
    """POST /settings/{slug}/secrets with an empty/missing CSRF token must return 403."""
    slug = seeded["proj"].slug
    user_email = seeded["user"].email

    session_cookie = _login(client, user_email, "jk-pass")
    resp = client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "openai", "secret": "sk-bad", "csrf_token": ""},
        cookies={"ts_session": session_cookie},
    )
    assert resp.status_code == 403


def test_settings_delete_secret_removes_it_from_config(
    db_session: Session,
    client: TestClient,
    seeded: dict,
) -> None:
    """POST /settings/{slug}/secrets/{provider}/delete removes the key; config returns empty."""
    proj = seeded["proj"]
    slug = proj.slug
    raw_key = seeded["raw_key"]
    user_email = seeded["user"].email

    session_cookie = _login(client, user_email, "jk-pass")
    auth = {"ts_session": session_cookie}

    # Add an openai key
    csrf = _get_csrf(client, slug, auth)
    client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "openai", "secret": "sk-to-delete", "csrf_token": csrf},
        cookies={**auth, CSRF_COOKIE: csrf},
    )

    # Verify config returns it before deletion
    config_before = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert config_before.json()["judge_keys"].get("openai") == "sk-to-delete"

    # Delete via the Settings form
    csrf2 = _get_csrf(client, slug, auth)
    del_resp = client.post(
        f"/settings/{slug}/secrets/openai/delete",
        data={"csrf_token": csrf2},
        cookies={**auth, CSRF_COOKIE: csrf2},
    )
    assert del_resp.status_code == 303

    # Config returns empty after deletion
    config_after = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert config_after.json() == {"judge_keys": {}}


def test_settings_page_with_multiple_providers_shows_both_masked(
    db_session: Session,
    client: TestClient,
    seeded: dict,
) -> None:
    """Settings page lists all configured providers as masked; neither plaintext appears."""
    proj = seeded["proj"]
    slug = proj.slug
    user_email = seeded["user"].email

    session_cookie = _login(client, user_email, "jk-pass")
    auth = {"ts_session": session_cookie}

    # Add openai
    csrf1 = _get_csrf(client, slug, auth)
    client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "openai", "secret": _OPENAI_PLAINTEXT, "csrf_token": csrf1},
        cookies={**auth, CSRF_COOKIE: csrf1},
    )

    # Add anthropic
    csrf2 = _get_csrf(client, slug, auth)
    client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "anthropic", "secret": _ANTHROPIC_PLAINTEXT, "csrf_token": csrf2},
        cookies={**auth, CSRF_COOKIE: csrf2},
    )

    # GET Settings page
    settings_resp = client.get(f"/settings/{slug}", cookies=auth)
    assert settings_resp.status_code == 200
    html = settings_resp.text

    # Both providers must be listed
    assert "openai" in html
    assert "anthropic" in html

    # Neither plaintext key must appear
    assert _OPENAI_PLAINTEXT not in html, (
        "openai plaintext must never be rendered on the Settings page"
    )
    assert _ANTHROPIC_PLAINTEXT not in html, (
        "anthropic plaintext must never be rendered on the Settings page"
    )

    # A provider containing a XSS payload is escaped by Jinja2 autoescape
    csrf3 = _get_csrf(client, slug, auth)
    client.post(
        f"/settings/{slug}/secrets",
        data={"provider": "<script>alert(1)</script>", "secret": "xss-val", "csrf_token": csrf3},
        cookies={**auth, CSRF_COOKIE: csrf3},
    )
    xss_resp = client.get(f"/settings/{slug}", cookies=auth)
    assert "<script>alert(1)</script>" not in xss_resp.text, (
        "Provider name containing <script> must be autoescaped by Jinja2"
    )
