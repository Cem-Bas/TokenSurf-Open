"""Round-trip ORM tests: Project → Run → CaseResult → Score against a real Postgres DB."""

from __future__ import annotations

import datetime

from tokensurf_server.models import CaseResult, Project, ProjectApiKey, Run, Score


def test_project_run_case_result_score_roundtrip(db_session):
    """Create the full hierarchy, flush, refresh, assert FKs and JSONB round-trips."""
    # --- Project ---
    project = Project(name="My Project", slug="my-project")
    db_session.add(project)
    db_session.flush()
    db_session.refresh(project)

    assert project.id is not None
    assert len(project.id) == 32  # new_id() → uuid4 hex
    assert project.slug == "my-project"
    assert isinstance(project.created_at, datetime.datetime)  # server_default populated

    # --- Run (JSONB source_metadata round-trip) ---
    source_meta: dict = {"git_sha": "abc123", "branch": "main"}
    run = Run(
        project_id=project.id,
        label="nightly",
        status="completed",
        n_cases=5,
        pass_rate=0.8,
        mean_score=0.75,
        error_count=1,
        source_metadata=source_meta,
    )
    db_session.add(run)
    db_session.flush()
    db_session.refresh(run)

    assert run.project_id == project.id
    assert run.source_metadata == source_meta  # JSONB round-trip

    # --- CaseResult (JSONB trace round-trip) ---
    trace_data: dict = {
        "id": "trace1",
        "name": "agent-run",
        "spans": [],
        "start": 1000.0,
        "end": 1002.0,
        "metadata": {},
    }
    case_result = CaseResult(
        run_id=run.id,
        case_id="case-001",
        input={"prompt": "What is 2+2?"},
        expected={"answer": "4"},
        output={"answer": "4"},
        trace=trace_data,
    )
    db_session.add(case_result)
    db_session.flush()
    db_session.refresh(case_result)

    assert case_result.run_id == run.id
    assert case_result.trace == trace_data  # JSONB round-trip
    assert case_result.input == {"prompt": "What is 2+2?"}

    # --- Score (JSONB raw round-trip) ---
    score = Score(
        run_id=run.id,
        case_result_id=case_result.id,
        scorer="exact_match",
        value=1.0,
        passed=True,
        error=None,
        raw={"detail": "matched"},
    )
    db_session.add(score)
    db_session.flush()
    db_session.refresh(score)

    assert score.case_result_id == case_result.id
    assert score.passed is True
    assert score.raw == {"detail": "matched"}  # JSONB round-trip


def test_project_api_key_nullable_fields(db_session):
    """ProjectApiKey.label and last_used_at are nullable; verify they round-trip as None."""
    project = Project(name="Key Test Project", slug="key-test")
    db_session.add(project)
    db_session.flush()

    api_key = ProjectApiKey(
        project_id=project.id,
        key_hash="a" * 64,
        key_prefix="tsk_abc123",
        label=None,
    )
    db_session.add(api_key)
    db_session.flush()
    db_session.refresh(api_key)

    assert api_key.project_id == project.id
    assert api_key.label is None
    assert api_key.last_used_at is None
    assert isinstance(api_key.created_at, datetime.datetime)
