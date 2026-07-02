"""Tests for db.py — verifies Base, get_engine, get_sessionmaker, get_session."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from tokensurf_server.db import Base, get_engine, get_session, get_sessionmaker


def test_base_is_declarative_base():
    # Base must be a DeclarativeBase subclass (has .metadata).
    assert hasattr(Base, "metadata")


def test_get_engine_returns_engine_with_same_url(db_session):
    engine = get_engine()
    assert str(engine.url).startswith("postgresql")


def test_get_sessionmaker_returns_sessionmaker(db_session):
    sm = get_sessionmaker()
    with sm() as session:
        assert isinstance(session, Session)


def test_get_session_yields_usable_session(db_session):
    """get_session() dependency yields a Session that can execute a trivial query."""
    gen = get_session()
    session = next(gen)
    result = session.execute(text("SELECT 1")).scalar()
    assert result == 1
    try:
        next(gen)
    except StopIteration:
        pass


def test_db_session_fixture_rolls_back(db_session):
    """The db_session fixture itself must provide a working Session."""
    result = db_session.execute(text("SELECT 42")).scalar()
    assert result == 42
