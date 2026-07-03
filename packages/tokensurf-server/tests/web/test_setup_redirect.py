"""Tests that /login and login_required redirect to /setup while no users exist."""

from __future__ import annotations

import os

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SESSION_SECRET", "test-only-secret-for-e2e-tests!")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.app import app
from tokensurf_server.db import get_session
from tokensurf_server.models import User
from tokensurf_server.security import hash_password


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, follow_redirects=False, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


def test_login_redirects_to_setup_when_no_users_exist(client: TestClient) -> None:
    resp = client.get("/login")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/setup")


def test_login_shows_form_when_a_user_exists(client: TestClient, db_session: Session) -> None:
    db_session.add(User(id=new_id(), email="a@example.test", password_hash=hash_password("x")))
    db_session.flush()
    resp = client.get("/login")
    assert resp.status_code == 200


def test_dashboard_redirects_to_setup_when_no_users_exist(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/setup")


def test_dashboard_redirects_to_login_when_a_user_exists_but_unauthenticated(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(User(id=new_id(), email="a@example.test", password_hash=hash_password("x")))
    db_session.flush()
    resp = client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/login")
