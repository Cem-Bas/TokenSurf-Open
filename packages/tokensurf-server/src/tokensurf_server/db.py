"""Database engine, session factory, and FastAPI session dependency."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from tokensurf_server.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    """Return a lazily-created SQLAlchemy engine (cached after first call)."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Return a lazily-created session factory (cached after first call)."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session():
    """FastAPI dependency: yield an open Session, close it in the finally block."""
    sm = get_sessionmaker()
    with sm() as session:
        yield session
