from tokensurf import EvalReport
from tokensurf.core.ids import new_id
from tokensurf.core.models import Case, EvalCaseResult, ScoreResult, Trace

from tokensurf_server.models import CaseResult, Project, Score
from tokensurf_server.service import persist_run, run_to_summary, summarize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report() -> EvalReport:
    """Two cases; one scorer with an error → status 'errored'."""
    case1 = Case(id=new_id(), input={"q": "What is 2+2?"}, expected={"a": "4"})
    trace1 = Trace(
        id=new_id(),
        name="agent",
        input={"q": "What is 2+2?"},
        output={"a": "4"},
        start=0.0,
        end=1.2,
    )
    score1a = ScoreResult(scorer="exact", value=1.0, passed=True)
    score1b = ScoreResult(scorer="fluency", value=0.9, passed=True)
    ecr1 = EvalCaseResult(case=case1, trace=trace1, scores=[score1a, score1b])

    case2 = Case(id=new_id(), input={"q": "Capital of Mars?"}, expected={"a": "N/A"})
    trace2 = Trace(
        id=new_id(),
        name="agent",
        input={"q": "Capital of Mars?"},
        output={"a": "Olympus"},
        start=0.0,
        end=0.8,
    )
    score2a = ScoreResult(scorer="exact", value=0.0, passed=False)
    score2b = ScoreResult.errored(scorer="fluency", error="judge timeout")
    ecr2 = EvalCaseResult(case=case2, trace=trace2, scores=[score2a, score2b])

    return EvalReport(results=[ecr1, ecr2])


# ---------------------------------------------------------------------------
# summarize() — pure-logic, no DB
# ---------------------------------------------------------------------------


def test_summarize_with_errors_sets_errored_status() -> None:
    report = _make_report()
    s = summarize(report)
    assert s["status"] == "errored"
    assert s["n_cases"] == 2
    assert s["error_count"] == 1
    assert abs(s["pass_rate"] - report.pass_rate()) < 1e-9
    assert s["mean_score"] == report.mean_score()


def test_summarize_all_passing_sets_completed_status() -> None:
    case = Case(id=new_id(), input="x", expected="y")
    score = ScoreResult(scorer="exact", value=1.0, passed=True)
    report = EvalReport(results=[EvalCaseResult(case=case, scores=[score])])
    s = summarize(report)
    assert s["status"] == "completed"
    assert s["error_count"] == 0
    assert s["n_cases"] == 1


def test_summarize_empty_report() -> None:
    report = EvalReport(results=[])
    s = summarize(report)
    assert s["status"] == "completed"
    assert s["n_cases"] == 0
    assert s["pass_rate"] == 0.0
    assert s["mean_score"] is None
    assert s["error_count"] == 0


# ---------------------------------------------------------------------------
# persist_run() — requires DB (db_session fixture from Group A's conftest.py)
# ---------------------------------------------------------------------------


def test_persist_run_creates_run_and_child_rows(db_session) -> None:
    report = _make_report()
    project = Project(id=new_id(), name="Persist Test", slug="persist-test")
    db_session.add(project)
    db_session.flush()

    run = persist_run(
        db_session,
        project=project,
        report=report,
        label="ci-run",
        metadata={"git_sha": "deadbeef"},
    )

    assert run.id is not None
    assert run.project_id == project.id
    assert run.label == "ci-run"
    assert run.source_metadata == {"git_sha": "deadbeef"}
    assert run.status == "errored"
    assert run.n_cases == 2
    assert run.error_count == 1
    assert abs(run.pass_rate - report.pass_rate()) < 1e-9

    from sqlalchemy import select

    case_results = list(db_session.scalars(select(CaseResult).where(CaseResult.run_id == run.id)))
    assert len(case_results) == 2

    scores = list(db_session.scalars(select(Score).where(Score.run_id == run.id)))
    assert len(scores) == 4  # 2 cases × 2 scorers


def test_persist_run_score_rows_match_scorers_and_errors(db_session) -> None:
    report = _make_report()
    project = Project(id=new_id(), name="Scorer Test", slug="scorer-test")
    db_session.add(project)
    db_session.flush()

    run = persist_run(
        db_session,
        project=project,
        report=report,
        label=None,
        metadata=None,
    )

    from sqlalchemy import select

    scores = list(db_session.scalars(select(Score).where(Score.run_id == run.id)))
    scorer_names = sorted({s.scorer for s in scores})
    assert scorer_names == ["exact", "fluency"]

    errored_scores = [s for s in scores if s.error is not None]
    assert len(errored_scores) == 1
    assert errored_scores[0].scorer == "fluency"
    assert errored_scores[0].value is None
    assert errored_scores[0].passed is None


def test_persist_run_case_result_rows_carry_trace_json(db_session) -> None:
    report = _make_report()
    project = Project(id=new_id(), name="Trace Test", slug="trace-test")
    db_session.add(project)
    db_session.flush()

    run = persist_run(
        db_session,
        project=project,
        report=report,
        label=None,
        metadata=None,
    )

    from sqlalchemy import select

    cr_rows = list(db_session.scalars(select(CaseResult).where(CaseResult.run_id == run.id)))
    for cr in cr_rows:
        assert cr.trace is not None
        assert "id" in cr.trace
        assert "spans" in cr.trace


def test_persist_run_no_metadata_allowed(db_session) -> None:
    case = Case(id=new_id(), input="ping", expected="pong")
    score = ScoreResult(scorer="exact", value=1.0, passed=True)
    report = EvalReport(results=[EvalCaseResult(case=case, scores=[score])])
    project = Project(id=new_id(), name="No Meta", slug="no-meta")
    db_session.add(project)
    db_session.flush()

    run = persist_run(
        db_session,
        project=project,
        report=report,
        label=None,
        metadata=None,
    )
    assert run.source_metadata is None


# ---------------------------------------------------------------------------
# run_to_summary()
# ---------------------------------------------------------------------------


def test_run_to_summary_maps_all_fields(db_session) -> None:
    report = _make_report()
    project = Project(id=new_id(), name="Summary Test", slug="summary-test")
    db_session.add(project)
    db_session.flush()

    run = persist_run(
        db_session,
        project=project,
        report=report,
        label="summary-label",
        metadata=None,
    )
    db_session.flush()

    summary = run_to_summary(run, project.slug)
    assert summary.run_id == run.id
    assert summary.project == project.slug
    assert summary.status == run.status
    assert summary.n_cases == 2
    assert abs(summary.pass_rate - report.pass_rate()) < 1e-9
    assert summary.error_count == 1
    assert summary.created_at is not None
