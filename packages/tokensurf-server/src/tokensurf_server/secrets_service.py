"""Service functions for managing per-project judge-key secrets.

Secrets are encrypted at rest using crypto.encrypt (Fernet, TOKENSURF_SECRET_KEY).
Plaintext is never stored; SecretKeyMissing is raised (never silently suppressed)
if the key is absent when encrypting or decrypting.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.crypto import decrypt, encrypt
from tokensurf_server.models import ProjectSecret


def set_secret(
    session: Session, *, project_id: str, provider: str, plaintext: str
) -> ProjectSecret:
    """Upsert a project secret by (project_id, provider).

    If a row for this (project_id, provider) already exists, its key_enc is updated
    (rotate by re-adding).  Otherwise a new row is inserted.  Calls session.flush()
    and returns the row.  Raises SecretKeyMissing if TOKENSURF_SECRET_KEY is unset.
    """
    row = session.scalar(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project_id,
            ProjectSecret.provider == provider,
        )
    )
    if row is not None:
        row.key_enc = encrypt(plaintext)
    else:
        row = ProjectSecret(
            id=new_id(),
            project_id=project_id,
            provider=provider,
            key_enc=encrypt(plaintext),
        )
        session.add(row)
    session.flush()
    return row


def list_providers(session: Session, project_id: str) -> list[str]:
    """Return provider names configured for *project_id*, sorted alphabetically."""
    rows = session.scalars(
        select(ProjectSecret.provider)
        .where(ProjectSecret.project_id == project_id)
        .order_by(ProjectSecret.provider)
    ).all()
    return list(rows)


def get_decrypted_secrets(session: Session, project_id: str) -> dict[str, str]:
    """Return ``{provider: plaintext}`` for all secrets of *project_id*.

    Raises SecretKeyMissing if TOKENSURF_SECRET_KEY is unset.  Never returns
    partially-decrypted results — if the key is missing the whole call fails.
    """
    rows = session.scalars(
        select(ProjectSecret).where(ProjectSecret.project_id == project_id)
    ).all()
    return {row.provider: decrypt(row.key_enc) for row in rows}


def delete_secret(session: Session, *, project_id: str, provider: str) -> bool:
    """Delete the secret for *(project_id, provider)*.

    Returns ``True`` if a row was deleted, ``False`` if no matching row existed.
    """
    row = session.scalar(
        select(ProjectSecret).where(
            ProjectSecret.project_id == project_id,
            ProjectSecret.provider == provider,
        )
    )
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True
