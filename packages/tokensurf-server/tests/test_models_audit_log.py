"""DB round-trip tests for the AuditLog ORM model (hardening B1)."""

from __future__ import annotations

from tokensurf.core.ids import new_id

from tokensurf_server.models import AuditLog


def test_audit_log_round_trip(db_session):
    log = AuditLog(
        id=new_id(),
        event="config.pull",
        project_id="proj-abc123",
        actor="api:ts_abcd",
        ip="127.0.0.1",
        detail={"key_count": 3},
    )
    db_session.add(log)
    db_session.flush()
    db_session.refresh(log)

    assert log.event == "config.pull"
    assert log.project_id == "proj-abc123"
    assert log.actor == "api:ts_abcd"
    assert log.ip == "127.0.0.1"
    assert log.detail == {"key_count": 3}
    assert log.created_at is not None


def test_audit_log_nullable_fields(db_session):
    log = AuditLog(id=new_id(), event="secret.set")
    db_session.add(log)
    db_session.flush()
    db_session.refresh(log)

    assert log.project_id is None
    assert log.actor is None
    assert log.ip is None
    assert log.detail is None
    assert log.created_at is not None


def test_audit_log_no_fk_constraint_on_project_id(db_session):
    """project_id carries no FK — audit rows outlive projects."""
    log = AuditLog(
        id=new_id(),
        event="config.pull",
        project_id="nonexistent-project-id-does-not-exist",
    )
    db_session.add(log)
    # Must not raise IntegrityError (no FK on project_id).
    db_session.flush()
    db_session.refresh(log)
    assert log.project_id == "nonexistent-project-id-does-not-exist"
