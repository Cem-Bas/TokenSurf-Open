from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def test_create_and_read_user(db_session) -> None:
    """User can be inserted and retrieved by email; created_at is populated by server."""
    from tokensurf.core.ids import new_id

    from tokensurf_server.models import User

    user = User(
        id=new_id(),
        email="alice@example.com",
        password_hash="pbkdf2$240000$deadbeef01$cafebabe01",
    )
    db_session.add(user)
    db_session.flush()

    fetched = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert fetched is not None
    assert fetched.email == "alice@example.com"
    assert fetched.password_hash == "pbkdf2$240000$deadbeef01$cafebabe01"
    assert fetched.created_at is not None


def test_user_email_unique_constraint(db_session) -> None:
    """Inserting two Users with the same email raises IntegrityError."""
    from tokensurf.core.ids import new_id

    from tokensurf_server.models import User

    email = "bob@example.com"
    db_session.add(User(id=new_id(), email=email, password_hash="hash-a"))
    db_session.flush()

    db_session.add(User(id=new_id(), email=email, password_hash="hash-b"))
    with pytest.raises(IntegrityError):
        db_session.flush()
