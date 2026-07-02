"""Tests for SecretView + list_secrets added in Slice 2d."""

from __future__ import annotations

import os

os.environ.setdefault("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET", "1")
os.environ.setdefault("TOKENSURF_SECRET_KEY", "test-secret-key")

from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.crypto import encrypt
from tokensurf_server.models import Project, ProjectSecret


def test_list_secrets_returns_none_for_unknown_slug(db_session: Session) -> None:
    from tokensurf_server.web.queries import list_secrets

    result = list_secrets(db_session, "no-such-slug-" + new_id()[:8])
    assert result is None


def test_list_secrets_returns_empty_list_for_project_with_no_secrets(
    db_session: Session,
) -> None:
    from tokensurf_server.web.queries import list_secrets

    proj = Project(id=new_id(), name="Empty Secrets", slug="empty-sec-" + new_id()[:6])
    db_session.add(proj)
    db_session.flush()

    result = list_secrets(db_session, proj.slug)
    assert result == []


def test_list_secrets_returns_secret_view_with_provider_and_has_value(
    db_session: Session,
) -> None:
    from tokensurf_server.web.queries import SecretView, list_secrets

    proj = Project(id=new_id(), name="One Secret", slug="one-sec-" + new_id()[:6])
    db_session.add(proj)
    db_session.add(
        ProjectSecret(
            id=new_id(),
            project_id=proj.id,
            provider="openai",
            key_enc=encrypt("sk-test-value"),
        )
    )
    db_session.flush()

    result = list_secrets(db_session, proj.slug)
    assert result is not None
    assert len(result) == 1
    sv = result[0]
    assert isinstance(sv, SecretView)
    assert sv.provider == "openai"
    assert sv.has_value is True
    assert not hasattr(sv, "key_enc")
    assert not hasattr(sv, "plaintext")


def test_list_secrets_sorted_by_provider(db_session: Session) -> None:
    from tokensurf_server.web.queries import list_secrets

    proj = Project(id=new_id(), name="Sorted Secrets", slug="sorted-sec-" + new_id()[:6])
    db_session.add(proj)
    for provider in ["openai", "anthropic", "gemini"]:
        db_session.add(
            ProjectSecret(
                id=new_id(),
                project_id=proj.id,
                provider=provider,
                key_enc=encrypt(f"key-{provider}"),
            )
        )
    db_session.flush()

    result = list_secrets(db_session, proj.slug)
    assert result is not None
    assert [sv.provider for sv in result] == ["anthropic", "gemini", "openai"]
