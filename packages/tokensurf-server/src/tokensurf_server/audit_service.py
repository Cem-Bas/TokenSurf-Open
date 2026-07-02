"""Audit logging service for tokensurf-server.

record() inserts an AuditLog row and flushes; the caller is responsible for
committing the surrounding transaction.

recent() returns the newest-first AuditView list for a project.

SECURITY: detail must never contain plaintext secret values — only safe
metadata such as key counts or provider names.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.models import AuditLog


@dataclass
class AuditView:
    event: str
    actor: str | None
    ip: str | None
    detail: dict | None
    created_at: datetime.datetime


def record(
    session: Session,
    *,
    event: str,
    project_id: str | None = None,
    actor: str | None = None,
    ip: str | None = None,
    detail: dict | None = None,
) -> None:
    """Insert an AuditLog row and flush.  Caller must commit.

    Never pass plaintext secret values in detail — use counts or provider names only.
    """
    log = AuditLog(
        id=new_id(),
        event=event,
        project_id=project_id,
        actor=actor,
        ip=ip,
        detail=detail,
    )
    session.add(log)
    session.flush()


def recent(session: Session, project_id: str, limit: int = 20) -> list[AuditView]:
    """Return the newest-first AuditLog rows for a project, mapped to AuditView."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        AuditView(
            event=r.event,
            actor=r.actor,
            ip=r.ip,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
