"""DB tests for tokensurf_server.pipeline.evaluate_and_notify."""

from __future__ import annotations

import pytest
from tokensurf import EvalReport
from tokensurf.core.ids import new_id

from tokensurf_server.models import Project, QualityGate, Run, RunGateResult
from tokensurf_server.pipeline import evaluate_and_notify

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(*, pass_: bool = True) -> EvalReport:
    """Minimal one-case EvalReport; pass_ controls whether the score passes."""
    return EvalReport.model_validate(
        {
            "results": [
                {
                    "case": {"id": new_id(), "input": {"q": "hi"}, "expected": None},
                    "trace": {
                        "id": new_id(),
                        "name": "agent",
                        "input": {"q": "hi"},
                        "output": {"a": "x"},
                        "start": 0.0,
                        "end": 0.1,
                    },
                    "scores": [
                        {
                            "scorer": "exact",
                            "value": 1.0 if pass_ else 0.0,
                            "passed": pass_,
                        }
                    ],
                }
            ]
        }
    )


def _seed_project_and_run(db_session, *, pass_: bool = True):
    """Insert Project + Run; return (project, run, report)."""
    project = Project(id=new_id(), name="Pipeline Test", slug=f"pipe-{new_id()[:6]}")
    db_session.add(project)
    db_session.flush()

    report = _make_report(pass_=pass_)
    run = Run(
        id=new_id(),
        project_id=project.id,
        label="test-run",
        status="completed",
        n_cases=1,
        pass_rate=1.0 if pass_ else 0.0,
        mean_score=None,
        error_count=0,
        source_metadata=None,
    )
    db_session.add(run)
    db_session.flush()
    return project, run, report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_evaluate_and_notify_no_gates_returns_empty(db_session) -> None:
    project, run, report = _seed_project_and_run(db_session)
    results = evaluate_and_notify(db_session, project=project, run=run, report=report)
    assert results == []


def test_evaluate_and_notify_breaching_run_records_failed_gate_result(db_session) -> None:
    from sqlalchemy import select

    project, run, report = _seed_project_and_run(db_session, pass_=False)

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="strict-pass-rate",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    results = evaluate_and_notify(db_session, project=project, run=run, report=report)

    assert len(results) == 1
    assert results[0].name == "strict-pass-rate"
    assert results[0].passed is False

    rgr = db_session.scalar(select(RunGateResult).where(RunGateResult.run_id == run.id))
    assert rgr is not None
    assert rgr.passed is False
    assert rgr.gate_name == "strict-pass-rate"
    assert rgr.metric == "pass_rate"
    assert rgr.threshold == pytest.approx(0.9)


def test_evaluate_and_notify_passing_run_records_passed_gate_result(db_session) -> None:
    from sqlalchemy import select

    project, run, report = _seed_project_and_run(db_session, pass_=True)

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="easy-gate",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.5,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    results = evaluate_and_notify(db_session, project=project, run=run, report=report)

    assert len(results) == 1
    assert results[0].passed is True

    rgr = db_session.scalar(select(RunGateResult).where(RunGateResult.run_id == run.id))
    assert rgr is not None
    assert rgr.passed is True


def test_evaluate_and_notify_disabled_gate_is_skipped(db_session) -> None:
    from sqlalchemy import select

    project, run, report = _seed_project_and_run(db_session, pass_=False)

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="disabled-gate",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=False,
    )
    db_session.add(gate)
    db_session.flush()

    results = evaluate_and_notify(db_session, project=project, run=run, report=report)

    assert results == []
    count = db_session.scalar(select(RunGateResult).where(RunGateResult.run_id == run.id))
    assert count is None


def test_evaluate_and_notify_gate_eval_error_does_not_raise(db_session, monkeypatch) -> None:
    """If evaluate_gates crashes, evaluate_and_notify catches it, logs, and returns []."""
    import tokensurf_server.pipeline as pipeline_mod

    project, run, report = _seed_project_and_run(db_session)

    def _crashing(report, gates):
        raise RuntimeError("gate evaluator exploded")

    monkeypatch.setattr(pipeline_mod, "evaluate_gates", _crashing)

    # Must not raise; must return empty list
    results = evaluate_and_notify(db_session, project=project, run=run, report=report)
    assert results == []


def test_evaluate_and_notify_still_returns_after_breach_with_no_channels(db_session) -> None:
    """A breaching run with zero notification channels still returns GateResult list."""
    project, run, report = _seed_project_and_run(db_session, pass_=False)

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="gate-no-channels",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    results = evaluate_and_notify(db_session, project=project, run=run, report=report)

    assert len(results) == 1
    assert results[0].passed is False
