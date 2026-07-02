"""Tests for CSRF protection on POST /logout and the logout form token (Group D2)."""

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
from tokensurf_server.web.csrf import CSRF_COOKIE, issue_token


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
        email="logout-csrf@example.test",
        password_hash=hash_password("pass5678"),
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
        data={
            "email": "logout-csrf@example.test",
            "password": "pass5678",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return resp.cookies["ts_session"]


def test_post_logout_without_csrf_returns_403(client: TestClient) -> None:
    """POST /logout with no ts_csrf cookie and no form token must return 403."""
    resp = client.post("/logout", data={})
    assert resp.status_code == 403


def test_post_logout_with_valid_csrf_redirects_to_login(
    client: TestClient, seeded_user: User
) -> None:
    """POST /logout with a matching CSRF cookie+form pair must return 303 to /login."""
    token = issue_token()
    session_cookie = _login(client)
    resp = client.post(
        "/logout",
        data={"csrf_token": token},
        cookies={"ts_session": session_cookie, CSRF_COOKIE: token},
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/login")


def test_post_logout_clears_session_cookie(client: TestClient, seeded_user: User) -> None:
    """After a valid logout the response must set ts_session to Max-Age=0 (browser deletion)."""
    token = issue_token()
    session_cookie = _login(client)
    resp = client.post(
        "/logout",
        data={"csrf_token": token},
        cookies={"ts_session": session_cookie, CSRF_COOKIE: token},
    )
    assert resp.status_code == 303
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "ts_session" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header


def test_dashboard_logout_form_contains_csrf_token(client: TestClient, seeded_user: User) -> None:
    """GET / must render the logout form with a hidden csrf_token matching the ts_csrf cookie."""
    session_cookie = _login(client)
    resp = client.get("/", cookies={"ts_session": session_cookie})
    assert resp.status_code == 200
    csrf_cookie_value = resp.cookies.get(CSRF_COOKIE, "")
    assert csrf_cookie_value, "ts_csrf cookie must be set by CsrfMiddleware on GET /"
    assert f'name="csrf_token" value="{csrf_cookie_value}"' in resp.text, (
        "Logout form must embed the CSRF token as a hidden field"
    )
