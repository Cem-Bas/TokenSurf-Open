"""DB round-trip tests for the four ORM models added in slice 2c (A3)."""

from tokensurf.core.ids import new_id

from tokensurf_server.models import (
    NotificationChannel,
    NotificationLog,
    Project,
    QualityGate,
    Run,
    RunGateResult,
)


def _project(db_session) -> Project:
    p = Project(id=new_id(), name="Gates Test", slug="gates-" + new_id()[:8])
    db_session.add(p)
    db_session.flush()
    return p


def test_quality_gate_round_trip(db_session):
    p = _project(db_session)
    gate = QualityGate(
        id=new_id(),
        project_id=p.id,
        name="pass-rate floor",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
    )
    db_session.add(gate)
    db_session.flush()
    db_session.refresh(gate)
    assert gate.enabled is True  # server/default
    assert gate.threshold == 0.9
    assert gate.scorer is None
    assert gate.created_at is not None


def test_quality_gate_scorer_scoped(db_session):
    p = _project(db_session)
    gate = QualityGate(
        id=new_id(),
        project_id=p.id,
        name="scorer floor",
        metric="scorer_pass_rate",
        scorer="ExactMatch",
        comparison="gt",
        threshold=0.75,
    )
    db_session.add(gate)
    db_session.flush()
    assert gate.scorer == "ExactMatch"


def test_notification_channel_round_trip(db_session):
    p = _project(db_session)
    ch = NotificationChannel(
        id=new_id(),
        project_id=p.id,
        type="webhook",
        name="ops",
        secret_enc="gAAAAA-ciphertext",
        config={"to": "team@example.com"},
    )
    db_session.add(ch)
    db_session.flush()
    db_session.refresh(ch)
    assert ch.enabled is True
    assert ch.config == {"to": "team@example.com"}
    assert ch.secret_enc == "gAAAAA-ciphertext"


def test_run_gate_result_round_trip(db_session):
    p = _project(db_session)
    run = Run(
        id=new_id(),
        project_id=p.id,
        label="v1",
        status="completed",
        n_cases=8,
        pass_rate=0.5,
        mean_score=0.5,
        error_count=0,
        source_metadata=None,
    )
    db_session.add(run)
    db_session.flush()
    res = RunGateResult(
        id=new_id(),
        run_id=run.id,
        gate_id=new_id(),
        gate_name="pass-rate floor",
        metric="pass_rate",
        comparison="gte",
        threshold=0.9,
        actual=0.5,
        passed=False,
    )
    db_session.add(res)
    db_session.flush()
    db_session.refresh(res)
    assert res.passed is False
    assert res.actual == 0.5


def test_notification_log_round_trip(db_session):
    log = NotificationLog(id=new_id(), channel_id=new_id(), run_id=new_id(), ok=True, error=None)
    db_session.add(log)
    db_session.flush()
    db_session.refresh(log)
    assert log.ok is True
    assert log.error is None
