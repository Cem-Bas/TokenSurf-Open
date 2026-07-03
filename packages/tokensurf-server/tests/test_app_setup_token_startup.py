"""Verify the server prints the setup token at startup when no users exist.

_lifespan is an async context manager, but this codebase has no pytest-asyncio/anyio
pytest-plugin configured anywhere (verified: no `anyio_mode`, no `pytest.mark.asyncio`,
no `pytest.mark.anyio` in any existing test or pyproject.toml). Rather than add that
plugin dependency, drive the async context manager from a plain sync test via
asyncio.run() — no new test infrastructure needed.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy.orm import Session, sessionmaker
from tokensurf.core.ids import new_id

from tokensurf_server.app import _lifespan, create_app
from tokensurf_server.db import get_session
from tokensurf_server.models import User
from tokensurf_server.security import hash_password


def _run_lifespan_once(app) -> None:
    async def _enter_and_exit() -> None:
        async with _lifespan(app):
            pass

    asyncio.run(_enter_and_exit())


def test_startup_logs_setup_token_when_no_users(
    db_session: Session, caplog: pytest.LogCaptureFixture, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TOKENSURF_SETUP_TOKEN_PATH", str(tmp_path / "setup_token"))
    from tokensurf_server import config as server_config

    server_config.get_settings.cache_clear()

    app = create_app()

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    with caplog.at_level(logging.INFO):
        _run_lifespan_once(app)
    assert "/setup" in caplog.text
    assert "token" in caplog.text.lower()


def test_startup_does_not_log_setup_token_when_users_exist(
    db_session: Session, caplog: pytest.LogCaptureFixture, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TOKENSURF_SETUP_TOKEN_PATH", str(tmp_path / "setup_token"))
    from tokensurf_server import config as server_config

    server_config.get_settings.cache_clear()

    db_session.add(
        User(id=new_id(), email="existing@example.test", password_hash=hash_password("x"))
    )
    db_session.flush()

    # _lifespan opens its own Session via tokensurf_server.app.get_sessionmaker(), which is
    # bound to a *separate* Postgres connection from db_session's. Under READ COMMITTED
    # isolation the row just flushed (not committed) above is invisible on that other
    # connection. Patch get_sessionmaker so _lifespan's query joins db_session's own
    # connection/transaction instead — keeping this test fully isolated (rolled back by the
    # db_session fixture) without committing real rows to the shared test database.
    monkeypatch.setattr(
        "tokensurf_server.app.get_sessionmaker",
        lambda: sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )

    app = create_app()

    def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    with caplog.at_level(logging.INFO):
        _run_lifespan_once(app)
    assert "/setup" not in caplog.text
