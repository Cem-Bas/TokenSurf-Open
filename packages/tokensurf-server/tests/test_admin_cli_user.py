from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id
from typer.testing import CliRunner

_TEST_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf",
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _patch_db_url(monkeypatch):
    """Point the CLI and Settings cache at the test DB."""
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_db_rows(test_engine):
    """Snapshot user/project ids before each test; delete any new rows in teardown.

    The create-user CLI commits real rows into the shared dev DB; without this the
    suite leaks users every run. Mirrors test_admin_cli.py::_clean_db_rows so a full
    suite run leaves row counts unchanged.
    """
    from tokensurf_server.models import Project, User

    with Session(test_engine) as s:
        pre_project_ids = set(s.execute(select(Project.id)).scalars())
        pre_user_ids = set(s.execute(select(User.id)).scalars())

    yield

    with Session(test_engine) as s:
        new_project_ids = set(s.execute(select(Project.id)).scalars()) - pre_project_ids
        new_user_ids = set(s.execute(select(User.id)).scalars()) - pre_user_ids
        for pid in new_project_ids:
            s.execute(text("DELETE FROM project_api_keys WHERE project_id=:p"), {"p": pid})
            s.execute(text("DELETE FROM projects WHERE id=:p"), {"p": pid})
        for uid in new_user_ids:
            s.execute(text("DELETE FROM users WHERE id=:u"), {"u": uid})
        s.commit()


@pytest.fixture(scope="module")
def test_engine():
    """Module-scoped engine; creates all tables once before the module's tests run."""
    from sqlalchemy import create_engine

    from tokensurf_server.db import Base

    engine = create_engine(_TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_create_user_inserts_hashed_password(test_engine) -> None:
    """create-user persists a User row; password_hash verifies and contains no plaintext."""
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import User
    from tokensurf_server.security import verify_password

    email = f"create-user-{new_id()[:8]}@example.com"
    result = runner.invoke(cli_app, ["create-user", email, "--password", "s3cret!"])
    assert result.exit_code == 0, result.output
    assert f"user {email} created" in result.output

    with Session(test_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        assert verify_password("s3cret!", user.password_hash) is True
        assert "s3cret!" not in user.password_hash  # plaintext never stored


def test_create_user_duplicate_email_exits_nonzero(test_engine) -> None:
    """Second create-user with the same email exits 1 without crashing."""
    from tokensurf_server.admin_cli import app as cli_app

    email = f"dup-user-{new_id()[:8]}@example.com"
    r1 = runner.invoke(cli_app, ["create-user", email, "--password", "first-pw"])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(cli_app, ["create-user", email, "--password", "second-pw"])
    assert r2.exit_code != 0
