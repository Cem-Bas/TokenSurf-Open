"""DB round-trip tests for the ProjectSecret ORM model (slice 2d A1)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from tokensurf.core.ids import new_id

from tokensurf_server.models import Project, ProjectSecret


def _project(db_session) -> Project:
    p = Project(id=new_id(), name="Secret Test", slug="secrets-" + new_id()[:8])
    db_session.add(p)
    db_session.flush()
    return p


def test_project_secret_round_trip(db_session):
    p = _project(db_session)
    secret = ProjectSecret(
        id=new_id(),
        project_id=p.id,
        provider="openai",
        key_enc="gAAAAA-encrypted-ciphertext",
    )
    db_session.add(secret)
    db_session.flush()
    db_session.refresh(secret)
    assert secret.project_id == p.id
    assert secret.provider == "openai"
    assert secret.key_enc == "gAAAAA-encrypted-ciphertext"
    assert secret.created_at is not None


def test_project_secret_unique_constraint_project_provider(db_session):
    p = _project(db_session)
    db_session.add(
        ProjectSecret(id=new_id(), project_id=p.id, provider="anthropic", key_enc="enc-a")
    )
    db_session.flush()
    db_session.add(
        ProjectSecret(id=new_id(), project_id=p.id, provider="anthropic", key_enc="enc-b")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
