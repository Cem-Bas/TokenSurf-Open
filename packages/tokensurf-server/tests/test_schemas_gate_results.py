"""Tests for GateResultOut schema and run_to_summary gate_results integration.

Pure schema/model tests need no DB. run_to_summary tests use db_session to
obtain a real Run ORM row; GateResult instances are constructed in memory
(pure dataclass, no session needed).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tokensurf import EvalReport
from tokensurf.core.ids import new_id
from tokensurf.core.models import Case, EvalCaseResult, ScoreResult

from tokensurf_server.gates import GateResult
from tokensurf_server.models import Project
from tokensurf_server.schemas import GateResultOut, RunSummary
from tokensurf_server.service import persist_run, run_to_summary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_case_report() -> EvalReport:
    c = Case(id=new_id(), input="ping", expected="pong")
    score = ScoreResult(scorer="exact", value=1.0, passed=True)
    return EvalReport(results=[EvalCaseResult(case=c, scores=[score])])


def _make_gate_result(
    *,
    name: str = "accuracy",
    metric: str = "pass_rate",
    passed: bool = False,
    actual: float | None = 0.75,
    threshold: float = 0.9,
) -> GateResult:
    return GateResult(
        gate_id=new_id(),
        name=name,
        metric=metric,
        scorer=None,
        comparison="gte",
        threshold=threshold,
        actual=actual,
        passed=passed,
    )


# ---------------------------------------------------------------------------
# GateResultOut — pure Pydantic model tests
# ---------------------------------------------------------------------------


def test_gate_result_out_all_fields() -> None:
    out = GateResultOut(
        name="accuracy", metric="pass_rate", passed=True, actual=0.95, threshold=0.9
    )
    assert out.name == "accuracy"
    assert out.metric == "pass_rate"
    assert out.passed is True
    assert out.actual == 0.95
    assert out.threshold == 0.9


def test_gate_result_out_actual_nullable() -> None:
    out = GateResultOut(
        name="quality", metric="mean_score", passed=True, actual=None, threshold=0.5
    )
    assert out.actual is None
    data = out.model_dump(mode="json")
    assert data["actual"] is None


def test_gate_result_out_serializes_to_json_dict() -> None:
    out = GateResultOut(
        name="gate-1", metric="scorer_pass_rate", passed=False, actual=0.4, threshold=0.8
    )
    data = out.model_dump(mode="json")
    assert data == {
        "name": "gate-1",
        "metric": "scorer_pass_rate",
        "passed": False,
        "actual": 0.4,
        "threshold": 0.8,
    }


# ---------------------------------------------------------------------------
# RunSummary.gate_results — default and explicit
# ---------------------------------------------------------------------------


def test_run_summary_gate_results_defaults_to_empty() -> None:
    now = datetime(2024, 6, 1, tzinfo=UTC)
    summary = RunSummary(
        run_id="r1",
        project="proj",
        status="completed",
        n_cases=1,
        pass_rate=1.0,
        mean_score=None,
        error_count=0,
        created_at=now,
    )
    assert summary.gate_results == []


def test_run_summary_accepts_gate_results() -> None:
    now = datetime(2024, 6, 1, tzinfo=UTC)
    gr = GateResultOut(name="acc", metric="pass_rate", passed=False, actual=0.5, threshold=0.9)
    summary = RunSummary(
        run_id="r2",
        project="proj",
        status="completed",
        n_cases=2,
        pass_rate=0.5,
        mean_score=None,
        error_count=0,
        created_at=now,
        gate_results=[gr],
    )
    assert len(summary.gate_results) == 1
    assert summary.gate_results[0].name == "acc"
    assert summary.gate_results[0].passed is False


def test_run_summary_gate_results_appears_in_serialized_json() -> None:
    now = datetime(2024, 6, 1, tzinfo=UTC)
    gr = GateResultOut(name="latency", metric="mean_score", passed=True, actual=0.9, threshold=0.7)
    summary = RunSummary(
        run_id="r3",
        project="proj",
        status="completed",
        n_cases=1,
        pass_rate=1.0,
        mean_score=0.9,
        error_count=0,
        created_at=now,
        gate_results=[gr],
    )
    data = summary.model_dump(mode="json")
    assert "gate_results" in data
    assert data["gate_results"][0]["name"] == "latency"
    assert data["gate_results"][0]["passed"] is True


# ---------------------------------------------------------------------------
# run_to_summary — backward-compat (no gate_results arg) + new arg
# ---------------------------------------------------------------------------


def test_run_to_summary_no_gate_results_arg_unchanged(db_session) -> None:
    """Existing callers that omit gate_results still get gate_results=[]."""
    project = Project(id=new_id(), name="BW Compat", slug="bw-compat")
    db_session.add(project)
    db_session.flush()
    run = persist_run(
        db_session, project=project, report=_one_case_report(), label=None, metadata=None
    )
    db_session.flush()

    summary = run_to_summary(run, project.slug)

    assert summary.run_id == run.id
    assert summary.project == project.slug
    assert summary.gate_results == []


def test_run_to_summary_with_gate_results_maps_to_out(db_session) -> None:
    """gate_results=[GateResult, ...] → RunSummary.gate_results=[GateResultOut, ...]."""
    project = Project(id=new_id(), name="Gate Map", slug="gate-map")
    db_session.add(project)
    db_session.flush()
    run = persist_run(
        db_session, project=project, report=_one_case_report(), label=None, metadata=None
    )
    db_session.flush()

    gr = _make_gate_result(
        name="accuracy", metric="pass_rate", passed=False, actual=0.75, threshold=0.9
    )
    summary = run_to_summary(run, project.slug, gate_results=[gr])

    assert len(summary.gate_results) == 1
    out = summary.gate_results[0]
    assert out.name == "accuracy"
    assert out.metric == "pass_rate"
    assert out.passed is False
    assert out.actual is not None and abs(out.actual - 0.75) < 1e-9
    assert out.threshold == 0.9


def test_run_to_summary_multiple_gate_results_preserved(db_session) -> None:
    project = Project(id=new_id(), name="Multi Gate", slug="multi-gate")
    db_session.add(project)
    db_session.flush()
    run = persist_run(
        db_session, project=project, report=_one_case_report(), label=None, metadata=None
    )
    db_session.flush()

    grs = [
        _make_gate_result(
            name="gate-A", metric="pass_rate", passed=True, actual=0.95, threshold=0.9
        ),
        _make_gate_result(
            name="gate-B", metric="mean_score", passed=False, actual=0.3, threshold=0.5
        ),
    ]
    summary = run_to_summary(run, project.slug, gate_results=grs)

    assert len(summary.gate_results) == 2
    names = [r.name for r in summary.gate_results]
    assert names == ["gate-A", "gate-B"]


def test_run_to_summary_empty_gate_results_list(db_session) -> None:
    project = Project(id=new_id(), name="Empty Gates", slug="empty-gates")
    db_session.add(project)
    db_session.flush()
    run = persist_run(
        db_session, project=project, report=_one_case_report(), label=None, metadata=None
    )
    db_session.flush()

    summary = run_to_summary(run, project.slug, gate_results=[])
    assert summary.gate_results == []


def test_run_to_summary_none_actual_gate_result_preserved(db_session) -> None:
    """actual=None (mean_score on all-errored) survives the mapping."""
    project = Project(id=new_id(), name="None Actual", slug="none-actual")
    db_session.add(project)
    db_session.flush()
    run = persist_run(
        db_session, project=project, report=_one_case_report(), label=None, metadata=None
    )
    db_session.flush()

    gr = _make_gate_result(
        name="quality", metric="mean_score", passed=True, actual=None, threshold=0.5
    )
    summary = run_to_summary(run, project.slug, gate_results=[gr])

    assert summary.gate_results[0].actual is None
    assert summary.gate_results[0].passed is True
