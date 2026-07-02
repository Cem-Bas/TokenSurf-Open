# tests/test_integration_e2e.py
"""Full end-to-end integration test: quality gate breach triggers webhook notification.

Seed project + API key + user via db_session (rolled back after test).
TOKENSURF_SECRET_KEY is set so crypto.encrypt/decrypt works.
tokensurf_server.notify.webhook._post is monkeypatched to capture calls
without making real HTTP requests.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.db import get_session
from tokensurf_server.models import (
    NotificationChannel,
    NotificationLog,
    Project,
    ProjectApiKey,
    QualityGate,
    RunGateResult,
    User,
)
from tokensurf_server.security import generate_api_key, hash_key, hash_password, key_prefix

_SECRET_KEY = "test-e2e-secret-key-32bytes!!!!!"
_WEBHOOK_URL = "https://hooks.example.com/e2e-test-webhook"


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
def seeded_e2e(db_session: Session):
    """Seed one project, one API key, one user."""
    slug = "e2e-proj-" + new_id()[:6]
    proj = Project(id=new_id(), name="E2E Project", slug=slug)
    db_session.add(proj)

    raw_key = generate_api_key()
    pak = ProjectApiKey(
        id=new_id(),
        project_id=proj.id,
        key_hash=hash_key(raw_key),
        key_prefix=key_prefix(raw_key),
        label="e2e-key",
    )
    db_session.add(pak)

    user = User(
        id=new_id(),
        email=f"e2e-{new_id()[:6]}@example.com",
        password_hash=hash_password("e2e-pass"),
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
    """Login and return the ts_session cookie value."""
    resp = client.post(
        "/login", data={"email": email, "password": password, "csrf_token": _csrf(client)}
    )
    assert resp.status_code == 303, f"login failed: {resp.status_code} {resp.text[:200]}"
    return resp.cookies["ts_session"]


def _breaching_report() -> dict:
    """Report with pass_rate = 0.0 (all cases failed); breaches a gate requiring >= 0.9."""
    return {
        "results": [
            {
                "case": {
                    "id": new_id(),
                    "input": {"q": "What is 2+2?"},
                    "expected": None,
                },
                "trace": {
                    "id": new_id(),
                    "name": "agent",
                    "input": {"q": "What is 2+2?"},
                    "output": {"a": "wrong"},
                    "start": 0.0,
                    "end": 0.1,
                },
                "scores": [{"scorer": "accuracy", "value": 0.0, "passed": False}],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


def test_full_pipeline_gate_breach_fires_webhook(
    db_session: Session,
    client: TestClient,
    seeded_e2e: dict,
    monkeypatch,
) -> None:
    """End-to-end: Settings form -> gate+channel creation -> ingest breach ->
    RunGateResult failed, WebhookNotifier._post called with decrypted URL,
    NotificationLog ok=True, run-detail page shows failed gate chip.
    """
    import tokensurf_server.notify.webhook as webhook_mod
    from tokensurf_server.web.csrf import CSRF_COOKIE

    # ── Monkeypatch webhook._post before any request ──────────────────────────
    captured: dict = {}

    def _fake_post(url: str, json: dict) -> None:
        captured["url"] = url
        captured["json"] = json

    monkeypatch.setattr(webhook_mod, "_post", _fake_post)

    proj = seeded_e2e["proj"]
    slug = proj.slug
    raw_key = seeded_e2e["raw_key"]
    user_email = seeded_e2e["user"].email

    # ── 1. Login ──────────────────────────────────────────────────────────────
    session_cookie = _login(client, user_email, "e2e-pass")
    auth = {"ts_session": session_cookie}

    # ── 2. GET /settings/{slug} to obtain CSRF cookie + token ────────────────
    get_resp = client.get(f"/settings/{slug}", cookies=auth)
    assert get_resp.status_code == 200, get_resp.text[:500]
    csrf_token = get_resp.cookies[CSRF_COOKIE]
    assert csrf_token, "GET /settings/{slug} must set the CSRF cookie"
    assert "pass-rate-gate" not in get_resp.text  # gate not yet created

    gate_cookies = {**auth, CSRF_COOKIE: csrf_token}

    # ── 3. POST /settings/{slug}/gates — create pass_rate >= 0.9 gate ────────
    gate_post = client.post(
        f"/settings/{slug}/gates",
        data={
            "name": "pass-rate-gate",
            "metric": "pass_rate",
            "scorer": "",
            "comparison": "gte",
            "threshold": "0.9",
            "csrf_token": csrf_token,
        },
        cookies=gate_cookies,
    )
    assert gate_post.status_code == 303, (
        f"Expected 303 redirect after gate creation, got {gate_post.status_code}: "
        f"{gate_post.text[:300]}"
    )

    # Verify gate row is in DB
    gate_row = db_session.scalar(
        select(QualityGate).where(
            QualityGate.project_id == proj.id,
            QualityGate.name == "pass-rate-gate",
        )
    )
    assert gate_row is not None, "QualityGate row must be committed after Settings POST"
    assert gate_row.metric == "pass_rate"
    assert gate_row.comparison == "gte"
    assert gate_row.threshold == pytest.approx(0.9)
    assert gate_row.enabled is True

    # ── 4. GET /settings/{slug} again for a fresh CSRF token ─────────────────
    get_resp2 = client.get(f"/settings/{slug}", cookies=auth)
    assert get_resp2.status_code == 200
    csrf_token2 = get_resp2.cookies[CSRF_COOKIE]
    channel_cookies = {**auth, CSRF_COOKIE: csrf_token2}

    # ── 5. POST /settings/{slug}/channels — create webhook channel ────────────
    # The channel's "secret" field holds the webhook URL; it will be encrypted at rest.
    channel_post = client.post(
        f"/settings/{slug}/channels",
        data={
            "type": "webhook",
            "name": "e2e-webhook",
            "secret": _WEBHOOK_URL,
            "to": "",
            "csrf_token": csrf_token2,
        },
        cookies=channel_cookies,
    )
    assert channel_post.status_code == 303, (
        f"Expected 303 after channel creation, got {channel_post.status_code}: "
        f"{channel_post.text[:300]}"
    )

    # Verify channel is in DB and secret is encrypted (never equals plaintext URL)
    chan_row = db_session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.project_id == proj.id,
            NotificationChannel.name == "e2e-webhook",
        )
    )
    assert chan_row is not None, "NotificationChannel row must exist"
    assert chan_row.secret_enc != _WEBHOOK_URL, "secret_enc must be the ciphertext, not the raw URL"
    assert chan_row.type == "webhook"
    assert chan_row.enabled is True

    # ── 6. Ingest a breaching run via the API ─────────────────────────────────
    ingest_resp = client.post(
        "/api/v1/runs",
        json={"label": "breach-run", "report": _breaching_report()},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert ingest_resp.status_code == 201, (
        f"Ingest must return 201; got {ingest_resp.status_code}: {ingest_resp.text[:300]}"
    )
    body = ingest_resp.json()
    run_id = body["run_id"]
    assert body["pass_rate"] == pytest.approx(0.0)

    # gate_results field in the run summary (from service.run_to_summary)
    gate_results_out = body.get("gate_results", [])
    assert len(gate_results_out) >= 1, (
        "RunSummary must include gate_results from evaluate_and_notify"
    )
    assert any(not gr["passed"] for gr in gate_results_out), (
        "At least one gate result must be failed (pass_rate 0.0 breaches gte 0.9)"
    )

    # ── 7. Assert RunGateResult row recorded with passed=False ───────────────
    rgr = db_session.scalar(select(RunGateResult).where(RunGateResult.run_id == run_id))
    assert rgr is not None, "RunGateResult row must be persisted by pipeline"
    assert rgr.passed is False
    assert rgr.gate_name == "pass-rate-gate"
    assert rgr.metric == "pass_rate"
    assert rgr.actual == pytest.approx(0.0)
    assert rgr.threshold == pytest.approx(0.9)

    # ── 8. Assert WebhookNotifier._post called with the DECRYPTED URL ────────
    assert captured, "webhook _post must have been called for the breach"
    assert captured["url"] == _WEBHOOK_URL, (
        f"_post must be called with the decrypted URL {_WEBHOOK_URL!r}; "
        f"got {captured.get('url')!r}. Secret must be decrypted before use."
    )
    webhook_payload = captured["json"]
    assert "failed_gates" in webhook_payload, "webhook payload must include failed_gates"
    assert any("pass-rate-gate" in str(g) for g in webhook_payload["failed_gates"]), (
        "failed_gates must include the gate name"
    )
    assert webhook_payload.get("run_id") == run_id
    # The raw URL must NOT appear in secret_enc (guard against plaintext storage)
    db_session.refresh(chan_row)
    assert _WEBHOOK_URL not in chan_row.secret_enc

    # ── 9. Assert NotificationLog ok=True row ────────────────────────────────
    notif_log = db_session.scalar(select(NotificationLog).where(NotificationLog.run_id == run_id))
    assert notif_log is not None, "NotificationLog row must be created by send_for_run"
    assert notif_log.ok is True, f"NotificationLog.ok must be True; error={notif_log.error!r}"
    assert notif_log.channel_id == chan_row.id

    # ── 10. Assert run-detail HTML page shows the failed gate chip ────────────
    detail_resp = client.get(f"/projects/{slug}/runs/{run_id}", cookies=auth)
    assert detail_resp.status_code == 200, detail_resp.text[:300]
    html = detail_resp.text
    assert "pass-rate-gate" in html, "run-detail page must show the gate name in a gate chip"
    # The chip must carry the 'fail' CSS class (gate not passed)
    # run.html renders: <span class="score-chip fail">pass-rate-gate …</span>
    assert "score-chip" in html, "gate result chips must use the .score-chip class"
    # Verify the failed chip is present by asserting the name appears near "fail"
    import re as _re

    fail_chip_pattern = _re.compile(r"score-chip\s+fail[^>]*>[^<]*pass-rate-gate", _re.IGNORECASE)
    assert fail_chip_pattern.search(html), (
        "run-detail page must render a .score-chip.fail chip with the gate name. "
        f"HTML snippet: "
        f"{html[html.find('pass-rate-gate') - 100 : html.find('pass-rate-gate') + 200]!r}"
    )
