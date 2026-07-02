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
    """Ensure the CLI uses the test DB and the settings cache sees it."""
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "test-secret-key")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def test_engine():
    """Engine pointing at the test DB with all tables created."""
    from sqlalchemy import create_engine

    from tokensurf_server.db import Base

    engine = create_engine(_TEST_DB_URL)
    try:
        import tokensurf_server.models  # noqa: F401 — register tables on Base.metadata
    except ModuleNotFoundError:
        pass
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# ── Cleanup helper (used by _db_cleanup fixture and tests) ────────────────────


def _delete_project_and_children(conn, project_id: str) -> None:
    """Delete a project and all its DB children, children first."""
    conn.execute(
        text(
            """
            DELETE FROM notification_logs
            WHERE channel_id IN (
                SELECT id FROM notification_channels WHERE project_id = :pid
            )
            """
        ),
        {"pid": project_id},
    )
    conn.execute(
        text(
            """
            DELETE FROM run_gate_results
            WHERE run_id IN (SELECT id FROM runs WHERE project_id = :pid)
            """
        ),
        {"pid": project_id},
    )
    conn.execute(
        text(
            """
            DELETE FROM scores
            WHERE run_id IN (SELECT id FROM runs WHERE project_id = :pid)
            """
        ),
        {"pid": project_id},
    )
    conn.execute(
        text(
            """
            DELETE FROM case_results
            WHERE run_id IN (SELECT id FROM runs WHERE project_id = :pid)
            """
        ),
        {"pid": project_id},
    )
    conn.execute(text("DELETE FROM runs WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(
        text("DELETE FROM notification_channels WHERE project_id = :pid"), {"pid": project_id}
    )
    conn.execute(text("DELETE FROM quality_gates WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM project_api_keys WHERE project_id = :pid"), {"pid": project_id})
    conn.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})


@pytest.fixture(autouse=True)
def _db_cleanup(test_engine):
    """Snapshot project/user IDs before each test; delete any new rows after.

    Uses a direct engine Connection so it bypasses get_session (which the
    _patch_db_url fixture may have redirected) and the CLI's own sessions.
    Children are deleted first to respect FK constraints.
    """

    def _snapshot(conn):
        proj_ids = {r[0] for r in conn.execute(text("SELECT id FROM projects")).fetchall()}
        user_ids = {r[0] for r in conn.execute(text("SELECT id FROM users")).fetchall()}
        return proj_ids, user_ids

    with test_engine.connect() as conn:
        before_proj, before_user = _snapshot(conn)

    yield

    with test_engine.connect() as conn:
        after_proj, after_user = _snapshot(conn)
        new_proj = after_proj - before_proj
        new_user = after_user - before_user

        for pid in new_proj:
            _delete_project_and_children(conn, pid)

        if new_user:
            conn.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": list(new_user)},
            )

        conn.commit()


def test_cleanup_removes_created_project(test_engine) -> None:
    """Verify _delete_project_and_children leaves no residue.

    Creates a project via CLI, asserts it exists, applies the cleanup
    logic inline, then asserts it is absent.
    """
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import Project

    slug = "cleanup-verify-" + new_id()[:8]
    result = runner.invoke(cli_app, ["create-project", "Cleanup Verify", "--slug", slug])
    assert result.exit_code == 0, result.output

    with test_engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM projects WHERE slug = :s"), {"s": slug}).fetchone()
        assert row is not None, "project must exist immediately after CLI creation"
        project_id = row[0]

    with test_engine.connect() as conn:
        _delete_project_and_children(conn, project_id)
        conn.commit()

    with Session(test_engine) as session:
        absent = session.scalar(select(Project).where(Project.slug == slug))
        assert absent is None, "project must be absent after _delete_project_and_children"
