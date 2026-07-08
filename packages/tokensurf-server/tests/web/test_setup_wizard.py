"""Tests for the first-run admin setup wizard (GET/POST /setup)."""

from __future__ import annotations

import os
import re

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server import config as server_config
from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import User
from tokensurf_server.security import hash_password, verify_password
from tokensurf_server.setup_token import get_or_create_token


@pytest.fixture(autouse=True)
def _setup_token_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "setup_token"
    monkeypatch.setenv("TOKENSURF_SETUP_TOKEN_PATH", str(path))
    server_config.get_settings.cache_clear()
    yield path
    server_config.get_settings.cache_clear()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, follow_redirects=False, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


def _csrf(client: TestClient, path: str = "/setup") -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', client.get(path).text)
    assert m is not None, f"csrf_token hidden field not found on {path}"
    return m.group(1)


def test_get_setup_shows_form_when_no_users_exist(client: TestClient) -> None:
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Create the admin account" in resp.text


def test_get_setup_redirects_to_login_when_a_user_exists(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(User(id=new_id(), email="a@example.test", password_hash=hash_password("x")))
    db_session.flush()
    resp = client.get("/setup")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/login")


def test_post_setup_creates_user_and_logs_in(
    client: TestClient, db_session: Session, _setup_token_path: Path
) -> None:
    token = get_or_create_token(_setup_token_path)
    resp = client.post(
        "/setup",
        data={
            "token": token,
            "email": "admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].endswith("/")
    assert "ts_session" in resp.cookies

    user = db_session.scalar(select(User).where(User.email == "admin@example.test"))
    assert user is not None
    assert verify_password("correct-horse-battery", user.password_hash)
    # Explicit "never plaintext" check, in addition to the verify_password round-trip above.
    assert user.password_hash != "correct-horse-battery"


def test_post_setup_rejects_wrong_token(
    client: TestClient, db_session: Session, _setup_token_path: Path
) -> None:
    get_or_create_token(_setup_token_path)
    resp = client.post(
        "/setup",
        data={
            "token": "not-the-real-token",
            "email": "admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 401
    assert db_session.scalar(select(User).where(User.email == "admin@example.test")) is None


def test_post_setup_rejects_when_a_user_already_exists(
    client: TestClient, db_session: Session, _setup_token_path: Path
) -> None:
    token = get_or_create_token(_setup_token_path)
    db_session.add(
        User(id=new_id(), email="existing@example.test", password_hash=hash_password("x"))
    )
    db_session.flush()
    resp = client.post(
        "/setup",
        data={
            "token": token,
            "email": "second-admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client, "/login"),
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/login")
    assert db_session.scalar(select(User).where(User.email == "second-admin@example.test")) is None


def test_post_setup_rejects_non_ascii_token(
    client: TestClient, db_session: Session, _setup_token_path: Path
) -> None:
    """A non-ASCII token must fail cleanly with 401, not crash compare_digest with a 500.

    secrets.compare_digest(str, str) raises TypeError on non-ASCII input; post_setup
    encodes both operands to bytes first specifically to avoid that.
    """
    get_or_create_token(_setup_token_path)
    resp = client.post(
        "/setup",
        data={
            "token": "not-the-real-token-éüñ",
            "email": "admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 401
    assert db_session.scalar(select(User).where(User.email == "admin@example.test")) is None


def test_post_setup_handles_integrity_error_as_double_submit(
    client: TestClient,
    db_session: Session,
    _setup_token_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a double-submit race: two requests both pass the any_user_exists()
    TOCTOU re-check before either commits, so the second commit hits the unique
    constraint on User.email and raises IntegrityError.

    Reproducing the real race deterministically (two concurrent requests actually
    interleaved at the DB level) isn't practical in a synchronous TestClient test.
    Instead we monkeypatch Session.commit to raise IntegrityError on the first call,
    directly exercising the new except-IntegrityError branch in post_setup: this
    verifies the actual behavior we care about (a friendly 303 to /login, not a 500)
    without depending on real thread/transaction timing.
    """
    from sqlalchemy.orm import Session as OrmSession

    token = get_or_create_token(_setup_token_path)
    real_commit = OrmSession.commit

    def _raise_integrity_error(self: Session) -> None:
        raise IntegrityError("INSERT INTO users ...", {}, Exception("duplicate key"))

    monkeypatch.setattr(OrmSession, "commit", _raise_integrity_error)
    resp = client.post(
        "/setup",
        data={
            "token": token,
            "email": "admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client),
        },
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].endswith("/login")
    assert "ts_session" not in resp.cookies

    # Restore real commit so cleanup (e.g. db_session fixture teardown) still works.
    monkeypatch.setattr(OrmSession, "commit", real_commit)


def test_post_setup_without_csrf_returns_403(client: TestClient, _setup_token_path: Path) -> None:
    token = get_or_create_token(_setup_token_path)
    resp = client.post(
        "/setup",
        data={"token": token, "email": "admin@example.test", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 403


def test_post_setup_rate_limited_returns_429(
    client: TestClient,
    db_session: Session,
    _setup_token_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the per-IP setup limit is exceeded, POST /setup returns 429 + Retry-After.

    Mirrors test_login_rate_limited_returns_429 in test_web_routes.py.
    """
    from tokensurf_server.ratelimit import SlidingWindowLimiter
    from tokensurf_server.web import routes

    get_or_create_token(_setup_token_path)
    monkeypatch.setattr(routes, "_setup_limiter", SlidingWindowLimiter(2, 60))
    # 2 attempts (wrong token -> 401) are allowed...
    for _ in range(2):
        r = client.post(
            "/setup",
            data={
                "token": "not-the-real-token",
                "email": "admin@example.test",
                "password": "correct-horse-battery",
                "csrf_token": _csrf(client),
            },
        )
        assert r.status_code == 401
    # ...the 3rd is throttled before the token check.
    r = client.post(
        "/setup",
        data={
            "token": "not-the-real-token",
            "email": "admin@example.test",
            "password": "correct-horse-battery",
            "csrf_token": _csrf(client),
        },
    )
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}
    assert db_session.scalar(select(User).where(User.email == "admin@example.test")) is None
