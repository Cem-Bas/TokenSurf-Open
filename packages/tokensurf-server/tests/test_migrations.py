"""Migration smoke test: upgrade head creates all five tables; downgrade base removes them.

DESTRUCTIVE: this drops every table in DATABASE_URL (drop_all + `alembic downgrade base`)
outside any rolled-back transaction, so it permanently wipes the target database. It is
SKIPPED by default to protect developer/dev databases; CI runs it against an ephemeral
Postgres service by setting TOKENSURF_DESTRUCTIVE_DB_TESTS=1.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from tokensurf_server.db import Base

pytestmark = pytest.mark.skipif(
    not os.environ.get("TOKENSURF_DESTRUCTIVE_DB_TESTS"),
    reason="drops every table in DATABASE_URL; set TOKENSURF_DESTRUCTIVE_DB_TESTS=1 "
    "against a throwaway database to run it",
)

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf",
)

_PACKAGE_DIR = Path(__file__).parent.parent  # packages/tokensurf-server/

_EXPECTED_TABLES = frozenset({"projects", "project_api_keys", "runs", "case_results", "scores"})


@pytest.fixture(scope="module")
def migration_engine():
    """Isolated engine for the migration test; restores schema at module teardown."""
    engine = create_engine(_DATABASE_URL)
    yield engine
    # Ensure tables are present for any tests that run after this module.
    Base.metadata.create_all(engine)
    engine.dispose()


def _alembic(command: str) -> None:
    """Run an alembic subcommand via uv in the package directory."""
    env = {**os.environ, "DATABASE_URL": _DATABASE_URL}
    result = subprocess.run(
        ["uv", "run", "--directory", str(_PACKAGE_DIR), "alembic"] + command.split(),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_PACKAGE_DIR),
    )
    assert result.returncode == 0, (
        f"`alembic {command}` failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _table_names(engine) -> frozenset[str]:
    return frozenset(inspect(engine).get_table_names())


def test_upgrade_then_downgrade(migration_engine):
    """
    Starting from a clean database:
      1. alembic upgrade head  → all five tables exist.
      2. alembic downgrade base → all five tables are gone.
      3. alembic upgrade head  → tables restored (so later tests still work).
    """
    # --- Start from a clean slate ---
    Base.metadata.drop_all(migration_engine)
    with migration_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # --- upgrade head ---
    _alembic("upgrade head")
    after_upgrade = _table_names(migration_engine)
    assert _EXPECTED_TABLES.issubset(after_upgrade), (
        f"Missing after upgrade: {_EXPECTED_TABLES - after_upgrade}"
    )

    # --- downgrade base ---
    _alembic("downgrade base")
    after_downgrade = _table_names(migration_engine)
    assert _EXPECTED_TABLES.isdisjoint(after_downgrade), (
        f"Still present after downgrade: {_EXPECTED_TABLES & after_downgrade}"
    )

    # --- restore so the session-scoped db_engine fixture still works ---
    _alembic("upgrade head")
    after_restore = _table_names(migration_engine)
    assert _EXPECTED_TABLES.issubset(after_restore), (
        f"Restore failed, missing: {_EXPECTED_TABLES - after_restore}"
    )
