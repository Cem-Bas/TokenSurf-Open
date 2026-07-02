"""Migration tests for 0003_gates_channels.

test_migration_0003_metadata — always runs; validates the migration file exists
and declares the correct revision chain before any DB is touched.

test_upgrade_0003_and_downgrade — destructive; guarded by
TOKENSURF_DESTRUCTIVE_DB_TESTS=1 (same pattern as test_migrations.py from 2b).
Set that env var only against a throwaway database; CI sets it on the ephemeral
Postgres service.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from tokensurf_server.db import Base

_PACKAGE_DIR = Path(__file__).parent.parent
_MIGRATION_FILE = _PACKAGE_DIR / "migrations" / "versions" / "0003_gates_channels.py"
_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf",
)
_NEW_TABLES = frozenset(
    {"quality_gates", "notification_channels", "run_gate_results", "notification_logs"}
)


# ---------------------------------------------------------------------------
# Non-destructive: validates the migration file exists and is correctly wired.
# ---------------------------------------------------------------------------


def test_migration_0003_file_exists_and_has_correct_revision():
    assert _MIGRATION_FILE.exists(), (
        f"Migration file not found: {_MIGRATION_FILE}. "
        "Create migrations/versions/0003_gates_channels.py."
    )
    spec = importlib.util.spec_from_file_location("migration_0003", _MIGRATION_FILE)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert module.revision == "0003", f"Expected revision='0003', got {module.revision!r}"
    assert module.down_revision == "0002", (
        f"Expected down_revision='0002', got {module.down_revision!r}"
    )


# ---------------------------------------------------------------------------
# Destructive: full upgrade → downgrade → upgrade cycle.
# ---------------------------------------------------------------------------

pytestmark_destructive = pytest.mark.skipif(
    not os.environ.get("TOKENSURF_DESTRUCTIVE_DB_TESTS"),
    reason=(
        "Drops and recreates schema. "
        "Set TOKENSURF_DESTRUCTIVE_DB_TESTS=1 against a throwaway database to run."
    ),
)


@pytest.fixture(scope="module")
def migration_engine():
    engine = create_engine(_DATABASE_URL)
    yield engine
    Base.metadata.create_all(engine)  # restore so later tests still have tables
    engine.dispose()


def _alembic(command: str) -> None:
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


@pytestmark_destructive
def test_upgrade_0003_adds_new_tables_and_downgrade_removes_them(migration_engine):
    # Start from a clean slate.
    Base.metadata.drop_all(migration_engine)
    with migration_engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Upgrade all the way to head (0001 → 0002 → 0003).
    _alembic("upgrade head")
    after_upgrade = _table_names(migration_engine)
    assert _NEW_TABLES.issubset(after_upgrade), (
        f"Missing after upgrade head: {_NEW_TABLES - after_upgrade}"
    )

    # Downgrade one step back to 0002; new tables must disappear.
    _alembic("downgrade 0002")
    after_downgrade_to_0002 = _table_names(migration_engine)
    assert _NEW_TABLES.isdisjoint(after_downgrade_to_0002), (
        f"Still present after downgrade to 0002: {_NEW_TABLES & after_downgrade_to_0002}"
    )
    # Older tables must survive the partial downgrade.
    assert {"projects", "runs", "users"}.issubset(after_downgrade_to_0002)

    # Restore to head so the session-scoped db_session fixture still works.
    _alembic("upgrade head")
    after_restore = _table_names(migration_engine)
    assert _NEW_TABLES.issubset(after_restore), (
        f"Restore failed, missing: {_NEW_TABLES - after_restore}"
    )
