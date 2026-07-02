"""Tests for CsrfMiddleware wired into the app (Group D1)."""

from __future__ import annotations

import os
import re

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server import config as server_config
from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import User
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
def seeded_user(db_session: Session) -> User:
    user = User(
        id=new_id(),
        email="csrf-mw@example.test",
        password_hash=hash_password("pass1234"),
    )
    db_session.add(user)
    db_session.flush()
    return user


def _csrf(client: TestClient) -> str:
    """GET /login (sets the ts_csrf cookie via CsrfMiddleware) and return its token."""
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get("/login").text)
    assert m is not None, "csrf_token hidden field not found on /login"
    return m.group(1)


def _login(client: TestClient) -> str:
    resp = client.post(
        "/login",
        data={"email": "csrf-mw@example.test", "password": "pass1234", "csrf_token": _csrf(client)},
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return resp.cookies["ts_session"]


def test_get_root_sets_ts_csrf_cookie(client: TestClient, seeded_user: User) -> None:
    """CsrfMiddleware must set the ts_csrf cookie on any response when the cookie is absent."""
    session_cookie = _login(client)
    resp = client.get("/", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    assert CSRF_COOKIE in resp.cookies, (
        f"Expected {CSRF_COOKIE!r} cookie in response; got {dict(resp.cookies)}"
    )


def test_existing_ts_csrf_cookie_value_is_preserved(client: TestClient, seeded_user: User) -> None:
    """Middleware must REUSE (not change) an already-present ts_csrf token value.

    The cookie is re-emitted on every response so it stays observable, but its VALUE
    must equal the token the client already holds (the double-submit invariant).
    """
    from tokensurf_server.web.csrf import issue_token

    existing_token = issue_token()
    session_cookie = _login(client)
    resp = client.get(
        "/",
        cookies={"ts_session": session_cookie, CSRF_COOKIE: existing_token},
    )
    assert resp.status_code == 200
    # Value must be preserved (never rotated) when the client already sent one.
    assert resp.cookies.get(CSRF_COOKIE) == existing_token
    # And the same token is embedded in the page for the double-submit form field.
    assert existing_token in resp.text


def test_invalid_ts_csrf_cookie_is_reissued(client: TestClient, seeded_user: User) -> None:
    """A tampered/unverifiable ts_csrf cookie must be replaced with a fresh valid token.

    Without re-issue, a rotated session_secret (or a planted garbage cookie) would be
    propagated forever and 403 every state-changing POST until the user clears cookies.
    """
    from itsdangerous import BadSignature

    from tokensurf_server.web.csrf import _serializer

    session_cookie = _login(client)
    garbage = "not-a-validly-signed-token"
    resp = client.get("/", cookies={"ts_session": session_cookie, CSRF_COOKIE: garbage})
    assert resp.status_code == 200
    fresh = resp.cookies.get(CSRF_COOKIE)
    assert fresh and fresh != garbage, "middleware must re-issue an unverifiable cookie"
    # The re-issued token must verify under the current secret...
    _serializer().loads(fresh)
    # ...and be the one embedded in the page's forms (self-healing double-submit).
    assert fresh in resp.text
    # Sanity: the garbage value would not have verified.
    try:
        _serializer().loads(garbage)
        raise AssertionError("garbage token unexpectedly verified")
    except BadSignature:
        pass


def test_ts_csrf_cookie_only_on_html_responses(client: TestClient) -> None:
    """The ts_csrf cookie is set on HTML pages but NOT on JSON endpoints.

    Gating on Content-Type (not path prefix) keeps the cookie off /healthz and
    /openapi.json (header noise / CDN concerns) while HTML forms still get it.
    """
    # HTML page → cookie present
    login = client.get("/login")
    assert login.headers["content-type"].startswith("text/html")
    assert CSRF_COOKIE in login.cookies

    # JSON endpoints → no ts_csrf Set-Cookie
    for path in ("/healthz", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "ts_csrf" not in resp.headers.get("set-cookie", ""), (
            f"{path} must not emit the ts_csrf cookie"
        )
