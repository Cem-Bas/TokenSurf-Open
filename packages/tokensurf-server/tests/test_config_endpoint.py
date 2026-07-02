"""Tests for GET /api/v1/config (Slice 2d Group B1)."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server import config as server_config
from tokensurf_server.app import create_app
from tokensurf_server.db import get_session
from tokensurf_server.models import Project, ProjectApiKey
from tokensurf_server.secrets_service import set_secret
from tokensurf_server.security import generate_api_key, hash_key, key_prefix


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    server_config.get_settings.cache_clear()
    yield
    server_config.get_settings.cache_clear()


@pytest.fixture
def config_setup(db_session: Session) -> Iterator[tuple]:
    """Seed project + api key + 2 provider secrets; yield (client, project, raw_key, secrets)."""
    project = Project(id=new_id(), name="Config Pull Project", slug="config-pull-proj")
    db_session.add(project)
    db_session.flush()

    raw_key = generate_api_key()
    pak = ProjectApiKey(
        id=new_id(),
        project_id=project.id,
        key_hash=hash_key(raw_key),
        key_prefix=key_prefix(raw_key),
        label="config-test-key",
    )
    db_session.add(pak)
    db_session.flush()

    secrets = {
        "openai": "sk-openai-test-secret-value",
        "anthropic": "sk-anthropic-test-secret-val",
    }
    for provider, plaintext in secrets.items():
        set_secret(db_session, project_id=project.id, provider=provider, plaintext=plaintext)
    db_session.flush()

    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, project, raw_key, secrets
    app.dependency_overrides.clear()


@pytest.fixture
def empty_setup(db_session: Session) -> Iterator[tuple]:
    """Project with no secrets."""
    project = Project(id=new_id(), name="Empty Config Project", slug="empty-config-proj")
    db_session.add(project)
    db_session.flush()

    raw_key = generate_api_key()
    pak = ProjectApiKey(
        id=new_id(),
        project_id=project.id,
        key_hash=hash_key(raw_key),
        key_prefix=key_prefix(raw_key),
        label="empty-config-key",
    )
    db_session.add(pak)
    db_session.flush()

    app = create_app()

    def _override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, raw_key
    app.dependency_overrides.clear()


def test_get_config_returns_both_decrypted_secrets(config_setup, caplog) -> None:
    client, _project, raw_key, secrets = config_setup
    with caplog.at_level(logging.DEBUG):
        resp = client.get(
            "/api/v1/config",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    data = resp.json()
    assert "judge_keys" in data
    assert data["judge_keys"]["openai"] == secrets["openai"]
    assert data["judge_keys"]["anthropic"] == secrets["anthropic"]
    for plaintext in secrets.values():
        assert plaintext not in caplog.text, f"Plaintext secret leaked into logs: {plaintext}"


def test_get_config_bad_bearer_returns_401(config_setup) -> None:
    client, _project, _raw_key, _secrets = config_setup
    resp = client.get(
        "/api/v1/config",
        headers={"Authorization": "Bearer tsk_totallyinvalidkey0000000000000000000000000"},
    )
    assert resp.status_code == 401


def test_get_config_missing_auth_returns_401(config_setup) -> None:
    client, _project, _raw_key, _secrets = config_setup
    resp = client.get("/api/v1/config")
    assert resp.status_code == 401


def test_get_config_no_secrets_returns_empty_judge_keys(empty_setup) -> None:
    client, raw_key = empty_setup
    resp = client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"judge_keys": {}}
