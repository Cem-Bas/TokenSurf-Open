from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tokensurf_server.schemas import IngestRunRequest, RunSummary


def test_ingest_run_request_minimal_valid() -> None:
    req = IngestRunRequest(report={"results": []})
    assert req.label is None
    assert req.metadata is None
    assert req.report == {"results": []}


def test_ingest_run_request_full() -> None:
    req = IngestRunRequest(
        label="nightly",
        report={"results": []},
        metadata={"git_sha": "abc123", "branch": "main"},
    )
    assert req.label == "nightly"
    assert req.metadata == {"git_sha": "abc123", "branch": "main"}


def test_ingest_run_request_report_required() -> None:
    with pytest.raises(ValidationError):
        IngestRunRequest()  # type: ignore[call-arg]


def test_run_summary_serializes_to_json_dict() -> None:
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    summary = RunSummary(
        run_id="run-abc",
        project="my-project",
        status="completed",
        n_cases=4,
        pass_rate=0.75,
        mean_score=0.8,
        error_count=0,
        created_at=now,
    )
    data = summary.model_dump(mode="json")
    assert data["run_id"] == "run-abc"
    assert data["project"] == "my-project"
    assert data["status"] == "completed"
    assert data["n_cases"] == 4
    assert data["pass_rate"] == 0.75
    assert data["mean_score"] == 0.8
    assert data["error_count"] == 0
    assert "created_at" in data


def test_run_summary_mean_score_nullable() -> None:
    now = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    summary = RunSummary(
        run_id="run-xyz",
        project="p",
        status="errored",
        n_cases=1,
        pass_rate=0.0,
        mean_score=None,
        error_count=1,
        created_at=now,
    )
    data = summary.model_dump(mode="json")
    assert data["mean_score"] is None
