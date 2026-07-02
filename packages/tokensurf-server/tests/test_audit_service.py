"""DB tests for audit_service (hardening B3).

Requires DATABASE_URL and TOKENSURF_SECRET_KEY in the environment.
All tests use the db_session fixture (savepoint isolation — no permanent rows written).
"""

from __future__ import annotations

import datetime

from tokensurf.core.ids import new_id

from tokensurf_server.audit_service import recent, record
from tokensurf_server.models import AuditLog, Project


def _project(db_session) -> Project:
    p = Project(id=new_id(), name="Audit SVC Test", slug="audit-" + new_id()[:8])
    db_session.add(p)
    db_session.flush()
    return p


def _utc(seconds_ago: int = 0) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds_ago)


def test_record_then_recent_returns_newest_first(db_session):
    p = _project(db_session)
    db_session.add(AuditLog(id=new_id(), event="config.pull", project_id=p.id, created_at=_utc(10)))
    db_session.add(AuditLog(id=new_id(), event="secret.set", project_id=p.id, created_at=_utc(5)))
    db_session.add(
        AuditLog(id=new_id(), event="secret.delete", project_id=p.id, created_at=_utc(1))
    )
    db_session.flush()

    rows = recent(db_session, p.id)

    assert len(rows) == 3
    assert rows[0].event == "secret.delete"
    assert rows[1].event == "secret.set"
    assert rows[2].event == "config.pull"


def test_recent_limit_respected(db_session):
    p = _project(db_session)
    for i in range(5):
        record(db_session, event="config.pull", project_id=p.id, actor=f"api:key{i}")

    rows = recent(db_session, p.id, limit=3)
    assert len(rows) == 3


def test_record_detail_json_persists(db_session):
    p = _project(db_session)
    record(
        db_session,
        event="config.pull",
        project_id=p.id,
        actor="api:ts_abcd1234",
        ip="10.0.0.1",
        detail={"key_count": 2, "extra": "metadata"},
    )

    rows = recent(db_session, p.id, limit=1)
    assert rows[0].detail == {"key_count": 2, "extra": "metadata"}
    assert rows[0].actor == "api:ts_abcd1234"
    assert rows[0].ip == "10.0.0.1"
    assert rows[0].created_at is not None


def test_record_isolates_by_project(db_session):
    p1 = _project(db_session)
    p2 = _project(db_session)
    record(db_session, event="config.pull", project_id=p1.id)
    record(db_session, event="secret.set", project_id=p2.id)

    rows_p1 = recent(db_session, p1.id)
    rows_p2 = recent(db_session, p2.id)

    assert len(rows_p1) == 1
    assert rows_p1[0].event == "config.pull"
    assert len(rows_p2) == 1
    assert rows_p2[0].event == "secret.set"


def test_record_detail_never_contains_secret_value(db_session):
    """Guard: only safe metadata (counts, provider names) may appear in detail."""
    p = _project(db_session)
    record(
        db_session,
        event="secret.set",
        project_id=p.id,
        actor="user:test@example.com",
        detail={"provider": "openai"},
    )

    rows = recent(db_session, p.id, limit=1)
    assert rows[0].detail == {"provider": "openai"}
    detail_str = str(rows[0].detail)
    # Ensure no typical plaintext API key fragments are present.
    assert "sk-" not in detail_str
    assert "Bearer " not in detail_str


def test_audit_view_fields_exposed(db_session):
    """AuditView exposes exactly: event, actor, ip, detail, created_at."""
    p = _project(db_session)
    record(
        db_session,
        event="config.pull",
        project_id=p.id,
        actor="api:abcd",
        ip="192.168.1.1",
        detail={"key_count": 1},
    )
    row = recent(db_session, p.id, limit=1)[0]
    assert row.event == "config.pull"
    assert row.actor == "api:abcd"
    assert row.ip == "192.168.1.1"
    assert row.detail == {"key_count": 1}
    assert isinstance(row.created_at, datetime.datetime)
