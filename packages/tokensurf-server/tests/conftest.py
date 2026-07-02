"""Shared pytest fixtures for tokensurf-server tests.

DB-touching tests use the `db_session` fixture: each test runs against a
Session bound to a Connection with an open outer transaction, and that
transaction is rolled back at teardown. `join_transaction_mode="create_savepoint"`
means any `session.commit()` inside application code (e.g. the ingest endpoint)
commits only a SAVEPOINT, so the outer rollback still fully isolates the test.
"""

from __future__ import annotations

import os

# Tests exercise the app with the built-in default session secret; opt in so the
# startup guard (which otherwise refuses to serve the UI with the public default)
# does not abort the suite. Production must NOT set this.
os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine as _create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from tokensurf_server.db import Base  # noqa: E402

_DEFAULT_DB_URL = "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"


@pytest.fixture(scope="session")
def engine():
    """One engine for the whole test session, pointing at the test Postgres.

    Imports the ORM models (once they exist) so every table is registered on
    Base.metadata before create_all. The guard keeps this conftest usable in
    Task A3 — before models.py is written — where no tables are needed yet.
    """
    url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    eng = _create_engine(url, pool_pre_ping=True)
    try:
        import tokensurf_server.models  # noqa: F401 — register tables on Base.metadata
    except ModuleNotFoundError:
        pass
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """Session joined to an external transaction; rolled back after each test.

    `create_savepoint` ensures application-level commits don't escape the
    per-test rollback (SQLAlchemy 2.0 'joining an external transaction' pattern).
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()
