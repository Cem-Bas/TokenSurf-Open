"""E2E tests for the Settings CRUD routes added to web/routes.py in slice 2c.

These tests exercise:
- GET /settings -> project picker (settings_index.html)
- GET /settings/{slug} -> per-project settings page; sets ts_csrf cookie
- POST /settings/{slug}/gates -> create gate; CSRF required
- POST /settings/{slug}/gates/{id}/delete -> delete gate; CSRF required
- POST /settings/{slug}/channels -> create channel; secret encrypted at rest
- POST /settings/{slug}/channels/{id}/delete -> delete channel; CSRF required
- POST /settings/{slug}/channels/{id}/test -> invoke notifier (mocked); CSRF required

Security invariants checked:
- Unauthenticated requests are rejected.
- Missing or tampered CSRF token -> 403.
- secret_enc plaintext never appears in any GET response.
"""

from __future__ import annotations

import os
import re

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id  # noqa: E402

from tokensurf_server import config as server_config
from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import NotificationChannel, Project, QualityGate, Run, User
from tokensurf_server.security import hash_password
from tokensurf_server.web.csrf import CSRF_COOKIE

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    proj = Project(id=new_id(), name="Settings Project", slug="settings-proj")
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
        email="admin@settings.test",
        password_hash=hash_password("pass1234"),
    )
    db_session.add(user)
    db_session.flush()
    return {"proj": proj, "run": run, "user": user}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(
    client: TestClient, email: str = "admin@settings.test", password: str = "pass1234"
) -> str:
    resp = client.post(
        "/login", data={"email": email, "password": password, "csrf_token": _csrf(client)}
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return resp.cookies["ts_session"]


def _authed(client: TestClient) -> str:
    return _login(client)


def _csrf_from_page(resp_text: str) -> str:
    """Extract the first hidden csrf_token value from rendered HTML."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp_text)
    assert m is not None, "csrf_token hidden field not found in HTML"
    return m.group(1)


# ---------------------------------------------------------------------------
# GET /settings — project picker
# ---------------------------------------------------------------------------


def test_settings_index_requires_login(client: TestClient, seeded: dict) -> None:
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_settings_index_renders_project_list(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.get("/settings", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert seeded["proj"].name in resp.text
    assert seeded["proj"].slug in resp.text


# ---------------------------------------------------------------------------
# GET /settings/{slug} — per-project settings page
# ---------------------------------------------------------------------------


def test_settings_detail_requires_login(client: TestClient, seeded: dict) -> None:
    resp = client.get("/settings/settings-proj", follow_redirects=False)
    assert resp.status_code == 303


def test_settings_detail_unknown_slug_returns_404(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.get("/settings/no-such-slug-xyz", cookies={"ts_session": cookie})
    assert resp.status_code == 404


def test_settings_detail_renders_and_sets_csrf_cookie(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert CSRF_COOKIE in resp.cookies, "ts_csrf cookie must be set on GET settings page"
    # Hidden form field present
    assert 'name="csrf_token"' in resp.text


def test_settings_detail_shows_quality_gates_and_channels_sections(
    client: TestClient, seeded: dict
) -> None:
    cookie = _authed(client)
    resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "Quality gates" in resp.text or "quality" in resp.text.lower()
    assert "Notification" in resp.text


# ---------------------------------------------------------------------------
# POST /settings/{slug}/gates — create gate (CSRF enforced)
# ---------------------------------------------------------------------------


def test_create_gate_missing_csrf_returns_403(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.post(
        "/settings/settings-proj/gates",
        data={
            "name": "No CSRF gate",
            "metric": "pass_rate",
            "comparison": "gte",
            "threshold": "0.9",
        },
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_create_gate_bad_csrf_returns_403(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.post(
        "/settings/settings-proj/gates",
        data={
            "name": "Bad CSRF gate",
            "metric": "pass_rate",
            "comparison": "gte",
            "threshold": "0.9",
            "csrf_token": "tampered.invalid.token",
        },
        cookies={"ts_session": cookie, CSRF_COOKIE: "also.wrong"},
    )
    assert resp.status_code == 403


def test_create_gate_valid_csrf_creates_gate_and_redirects(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    cookie = _authed(client)
    # GET page to obtain a signed CSRF token + set the cookie in the client jar
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    assert get_resp.status_code == 200
    csrf_token = _csrf_from_page(get_resp.text)

    post_resp = client.post(
        "/settings/settings-proj/gates",
        data={
            "name": "PR threshold",
            "metric": "pass_rate",
            "scorer": "",
            "comparison": "gte",
            "threshold": "0.85",
            "csrf_token": csrf_token,
        },
        cookies={"ts_session": cookie},
    )
    assert post_resp.status_code == 303
    assert post_resp.headers["location"].endswith("/settings/settings-proj")

    # Gate is persisted in the test session
    from sqlalchemy import select

    gates = (
        db_session.execute(select(QualityGate).where(QualityGate.project_id == seeded["proj"].id))
        .scalars()
        .all()
    )
    assert any(g.name == "PR threshold" for g in gates)


def test_create_gate_unknown_slug_returns_404(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    # Need a CSRF token — get it from an existing page
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    resp = client.post(
        "/settings/no-such-slug/gates",
        data={
            "name": "x",
            "metric": "pass_rate",
            "comparison": "gte",
            "threshold": "0.9",
            "csrf_token": csrf_token,
        },
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /settings/{slug}/gates/{gate_id}/delete
# ---------------------------------------------------------------------------


def test_delete_gate_missing_csrf_returns_403(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    gate = QualityGate(
        id=new_id(),
        project_id=seeded["proj"].id,
        name="To delete",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    cookie = _authed(client)
    resp = client.post(
        f"/settings/settings-proj/gates/{gate.id}/delete",
        data={},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_delete_gate_valid_csrf_removes_gate_and_redirects(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    gate = QualityGate(
        id=new_id(),
        project_id=seeded["proj"].id,
        name="Gate to remove",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    cookie = _authed(client)
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    resp = client.post(
        f"/settings/settings-proj/gates/{gate.id}/delete",
        data={"csrf_token": csrf_token},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303

    from sqlalchemy import select

    remaining = db_session.execute(
        select(QualityGate).where(QualityGate.id == gate.id)
    ).scalar_one_or_none()
    assert remaining is None


# ---------------------------------------------------------------------------
# POST /settings/{slug}/channels — create channel (secret encrypted)
# ---------------------------------------------------------------------------


def test_create_channel_missing_csrf_returns_403(client: TestClient, seeded: dict) -> None:
    cookie = _authed(client)
    resp = client.post(
        "/settings/settings-proj/channels",
        data={"name": "Slack", "type": "slack", "secret": "https://hooks.example.com/x"},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_create_channel_valid_csrf_encrypts_secret_and_redirects(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    cookie = _authed(client)
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    plaintext_secret = "https://hooks.slack.com/services/REAL/SECRET/URL"
    resp = client.post(
        "/settings/settings-proj/channels",
        data={
            "name": "My Slack",
            "type": "slack",
            "secret": plaintext_secret,
            "to": "",
            "csrf_token": csrf_token,
        },
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303

    from sqlalchemy import select

    channels = (
        db_session.execute(
            select(NotificationChannel).where(NotificationChannel.project_id == seeded["proj"].id)
        )
        .scalars()
        .all()
    )
    assert len(channels) == 1
    ch = channels[0]
    # Secret must be stored encrypted — ciphertext is not the plaintext
    assert ch.secret_enc != plaintext_secret
    assert plaintext_secret not in ch.secret_enc
    # Ciphertext must be non-empty
    assert len(ch.secret_enc) > 0


def test_create_channel_secret_never_in_get_response(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    """After creating a channel, the plaintext secret must never appear in any HTML response."""
    plaintext_secret = "super-secret-slack-url-do-not-render"

    # Seed a channel directly with an encrypted version
    from tokensurf_server.crypto import encrypt

    channel = NotificationChannel(
        id=new_id(),
        project_id=seeded["proj"].id,
        type="slack",
        name="Secret channel",
        secret_enc=encrypt(plaintext_secret),
        config=None,
        enabled=True,
    )
    db_session.add(channel)
    db_session.flush()

    cookie = _authed(client)
    resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert plaintext_secret not in resp.text, "Plaintext secret must never be rendered"
    assert channel.secret_enc not in resp.text, "Encrypted secret must never be rendered either"


# ---------------------------------------------------------------------------
# POST /settings/{slug}/channels/{channel_id}/delete
# ---------------------------------------------------------------------------


def test_delete_channel_valid_csrf_removes_channel(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    channel = NotificationChannel(
        id=new_id(),
        project_id=seeded["proj"].id,
        type="webhook",
        name="To remove",
        secret_enc="enc-placeholder",
        config=None,
        enabled=True,
    )
    db_session.add(channel)
    db_session.flush()

    cookie = _authed(client)
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    resp = client.post(
        f"/settings/settings-proj/channels/{channel.id}/delete",
        data={"csrf_token": csrf_token},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303

    from sqlalchemy import select

    remaining = db_session.execute(
        select(NotificationChannel).where(NotificationChannel.id == channel.id)
    ).scalar_one_or_none()
    assert remaining is None


# ---------------------------------------------------------------------------
# POST /settings/{slug}/channels/{channel_id}/test
# ---------------------------------------------------------------------------


def test_test_send_missing_csrf_returns_403(
    client: TestClient, seeded: dict, db_session: Session
) -> None:
    from tokensurf_server.crypto import encrypt

    channel = NotificationChannel(
        id=new_id(),
        project_id=seeded["proj"].id,
        type="slack",
        name="Test channel",
        secret_enc=encrypt("https://hooks.example.com"),
        config=None,
        enabled=True,
    )
    db_session.add(channel)
    db_session.flush()

    cookie = _authed(client)
    resp = client.post(
        f"/settings/settings-proj/channels/{channel.id}/test",
        data={},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 403


def test_test_send_invokes_notifier_and_redirects(
    client: TestClient, seeded: dict, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tokensurf_server.crypto import encrypt

    channel = NotificationChannel(
        id=new_id(),
        project_id=seeded["proj"].id,
        type="slack",
        name="Test channel",
        secret_enc=encrypt("https://hooks.example.com"),
        config=None,
        enabled=True,
    )
    db_session.add(channel)
    db_session.flush()

    mock_notifier = MagicMock()
    monkeypatch.setattr("tokensurf_server.notify.get_notifier", lambda _type: mock_notifier)

    cookie = _authed(client)
    get_resp = client.get("/settings/settings-proj", cookies={"ts_session": cookie})
    csrf_token = _csrf_from_page(get_resp.text)

    resp = client.post(
        f"/settings/settings-proj/channels/{channel.id}/test",
        data={"csrf_token": csrf_token},
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 303
    # Notifier's send() must have been called once
    mock_notifier.send.assert_called_once()
    call_kwargs = mock_notifier.send.call_args.kwargs
    assert call_kwargs["channel"].id == channel.id
    assert call_kwargs["failed_gates"] == []
