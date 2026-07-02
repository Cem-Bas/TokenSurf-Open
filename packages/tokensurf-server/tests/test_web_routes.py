"""End-to-end tests for the HTML dashboard (routes.py + app.py wiring).

Pattern:
  - `engine` fixture (session-scoped, from conftest) creates all tables once.
  - `db_session` fixture (function-scoped, from conftest) wraps each test in a
    rolled-back transaction so seeds never escape.
  - `client` fixture overrides `get_session` with the test db_session and wraps
    TestClient in its lifespan context.
  - `seeded` fixture inserts one project / one run / one case / two scores /
    one user into the test transaction, then flushes (visible to the same
    session without committing to the real DB).
"""

from __future__ import annotations

import os
import re

# Set before any tokensurf_server import so Settings() picks it up even if
# get_settings() was already cached in another test module during this session.
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")

from collections.abc import Iterator

import pytest
import tokensurf as _ts_config  # noqa: F401 — ensure package importable
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server import config as server_config
from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import CaseResult, Project, Run, Score, User
from tokensurf_server.security import hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure get_settings() re-reads env vars (including SESSION_SECRET) each test."""
    server_config.get_settings.cache_clear()
    yield
    server_config.get_settings.cache_clear()


@pytest.fixture
def client(db_session: Session):
    """TestClient with get_session overridden to the per-test rolled-back session."""

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, follow_redirects=False, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def seeded(db_session: Session) -> dict:
    """Seed one project, one run, one case (with trace), two scores, one user."""
    proj = Project(id=new_id(), name="Test Project", slug="test-proj")
    db_session.add(proj)

    run = Run(
        id=new_id(),
        project_id=proj.id,
        label="v1.0",
        status="completed",
        n_cases=1,
        pass_rate=0.75,
        mean_score=0.75,
        error_count=0,
    )
    db_session.add(run)

    case = CaseResult(
        id=new_id(),
        run_id=run.id,
        case_id="case-001",
        input={"question": "What is 2+2?"},
        expected=None,
        output={"answer": "4"},
        trace={
            "spans": [
                {
                    "type": "llm",
                    "name": "gpt-call",
                    "input": "What is 2+2?",
                    "output": "4",
                    "error": None,
                    "start": 0,
                    "end": 120,
                }
            ]
        },
    )
    db_session.add(case)

    score_pass = Score(
        id=new_id(),
        run_id=run.id,
        case_result_id=case.id,
        scorer="accuracy",
        value=0.9,
        passed=True,
        error=None,
    )
    score_fail = Score(
        id=new_id(),
        run_id=run.id,
        case_result_id=case.id,
        scorer="relevance",
        value=0.3,
        passed=False,
        error=None,
    )
    db_session.add(score_pass)
    db_session.add(score_fail)

    user = User(
        id=new_id(),
        email="admin@example.com",
        password_hash=hash_password("secret123"),
    )
    db_session.add(user)

    db_session.flush()
    return {"proj": proj, "run": run, "case": case, "user": user}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(client: TestClient, email: str = "admin@example.com", password: str = "secret123"):
    return client.post(
        "/login", data={"email": email, "password": password, "csrf_token": _csrf(client)}
    )


def _authed_cookie(client: TestClient) -> str:
    resp = _login(client)
    assert resp.status_code == 303, f"login failed: {resp.status_code} {resp.text[:200]}"
    return resp.cookies["ts_session"]


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------


def test_scorers_page_requires_login(client, seeded) -> None:
    resp = client.get("/scorers", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_settings_page_requires_login(client, seeded) -> None:
    resp = client.get("/settings", follow_redirects=False)
    assert resp.status_code == 303


def test_scorers_page_lists_families(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/scorers", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "LLMJudge" in resp.text
    assert "ToolSequence" in resp.text
    assert "EmbeddingSimilarity" in resp.text


def test_settings_page_renders(client, seeded) -> None:
    """GET /settings shows the project picker (settings index page)."""
    cookie = _authed_cookie(client)
    resp = client.get("/settings", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    # The index lists the seeded project by name and slug
    assert seeded["proj"].name in resp.text


def test_sidebar_nav_present_when_authenticated(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "sidebar" in resp.text
    assert 'href="/scorers"' in resp.text
    assert 'href="/settings"' in resp.text


def test_runs_page_requires_login(client, seeded) -> None:
    resp = client.get("/runs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_runs_page_lists_runs(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/runs", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    # the seeded run's project + a pass-rate chip render
    assert seeded["proj"].name in resp.text
    assert "score-chip" in resp.text


def test_runs_page_gate_filter_accepted(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/runs?gate=failed", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    # filter dropdown reflects the selection
    assert 'value="failed"' in resp.text


def test_docs_page_renders(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/docs", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "@ts.track" in resp.text
    assert "tokensurf eval run" in resp.text


def test_unauthenticated_root_redirects_to_login(client, seeded) -> None:
    resp = client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_post_login_bad_password_returns_401(client, seeded) -> None:
    # Pass CSRF so the request reaches the credential check (bad password -> 401).
    resp = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "wrongpass", "csrf_token": _csrf(client)},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.text


def test_post_login_unknown_email_returns_401(client, seeded) -> None:
    resp = client.post(
        "/login",
        data={"email": "ghost@nowhere.io", "password": "secret123", "csrf_token": _csrf(client)},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.text


def test_login_sets_httponly_cookie_and_redirects_to_root(client, seeded) -> None:
    resp = _login(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "ts_session" in resp.cookies
    # httponly flag must appear in the raw Set-Cookie header
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie_header.lower()


# ---------------------------------------------------------------------------
# Authenticated pages
# ---------------------------------------------------------------------------


def test_authed_root_shows_project_name(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert seeded["proj"].name in resp.text  # "Test Project"


def test_project_page_renders_trend_svg_and_run_rows(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/projects/test-proj", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "<svg" in resp.text, "trend SVG missing"
    assert seeded["run"].label in resp.text  # "v1.0"


def test_run_detail_shows_score_chips_and_scorer_stats(client, seeded) -> None:
    cookie = _authed_cookie(client)
    run_id = seeded["run"].id
    resp = client.get(f"/projects/test-proj/runs/{run_id}", cookies={"ts_session": cookie})
    assert resp.status_code == 200
    assert "score-chip" in resp.text, "score chip classes missing"
    assert "accuracy" in resp.text, "accuracy scorer missing"
    assert "relevance" in resp.text, "relevance scorer missing"
    assert "dist-bars" in resp.text, (
        "score distribution bars missing (route must set stat.bars_html)"
    )


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


def test_unknown_slug_returns_404(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get("/projects/no-such-project", cookies={"ts_session": cookie})
    assert resp.status_code == 404


def test_unknown_run_id_returns_404(client, seeded) -> None:
    cookie = _authed_cookie(client)
    resp = client.get(
        "/projects/test-proj/runs/00000000000000000000000000000000",
        cookies={"ts_session": cookie},
    )
    assert resp.status_code == 404


def test_cross_project_run_returns_404(client, seeded, db_session: Session) -> None:
    """A run belonging to test-proj must not be accessible via a different slug."""
    proj2 = Project(id=new_id(), name="Other Project", slug="other-proj")
    db_session.add(proj2)
    db_session.flush()

    cookie = _authed_cookie(client)
    run_id = seeded["run"].id
    resp = client.get(f"/projects/other-proj/runs/{run_id}", cookies={"ts_session": cookie})
    assert resp.status_code == 404


def test_post_login_without_csrf_returns_403(client, seeded) -> None:
    """Login CSRF: POST /login with no ts_csrf cookie and no form token must 403."""
    resp = client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    assert resp.status_code == 403


def test_post_login_with_valid_csrf_succeeds(client, seeded) -> None:
    """The GET-then-POST double-submit flow logs in normally (303)."""
    resp = _login(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
