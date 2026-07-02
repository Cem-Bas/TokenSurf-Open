import pytest
import pytest as _pytest  # alias used by gate-result tests
from fastapi.testclient import TestClient
from tokensurf.core.ids import new_id

from tokensurf_server.db import get_session
from tokensurf_server.models import Project, ProjectApiKey, QualityGate, Run, RunGateResult
from tokensurf_server.security import generate_api_key, hash_key, key_prefix

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ingest_setup(db_session):
    """Yields (TestClient, project, raw_api_key) with the session override wired in."""
    from tokensurf_server.app import create_app

    project = Project(id=new_id(), name="Ingest Test", slug="ingest-test")
    db_session.add(project)
    db_session.flush()

    raw_key = generate_api_key()
    pak = ProjectApiKey(
        id=new_id(),
        project_id=project.id,
        key_hash=hash_key(raw_key),
        key_prefix=key_prefix(raw_key),
        label="test-key",
    )
    db_session.add(pak)
    db_session.flush()

    app = create_app()

    def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, project, raw_key

    app.dependency_overrides.clear()


def _minimal_report_dict() -> dict:
    return {
        "results": [
            {
                "case": {"id": new_id(), "input": {"q": "hello"}, "expected": None},
                "trace": {
                    "id": new_id(),
                    "name": "agent",
                    "input": {"q": "hello"},
                    "output": {"a": "world"},
                    "start": 0.0,
                    "end": 0.5,
                },
                "scores": [{"scorer": "exact", "value": 1.0, "passed": True}],
            }
        ]
    }


# ---------------------------------------------------------------------------
# POST /api/v1/runs
# ---------------------------------------------------------------------------


def test_ingest_run_happy_path_returns_201(ingest_setup) -> None:
    client, project, raw_key = ingest_setup
    resp = client.post(
        "/api/v1/runs",
        json={"label": "ci", "report": _minimal_report_dict(), "metadata": {"git_sha": "abc"}},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["project"] == project.slug
    assert data["status"] == "completed"
    assert data["n_cases"] == 1
    assert data["error_count"] == 0
    assert "run_id" in data


def test_ingest_run_missing_auth_returns_401(ingest_setup) -> None:
    client, _project, _raw_key = ingest_setup
    resp = client.post(
        "/api/v1/runs",
        json={"report": _minimal_report_dict()},
    )
    assert resp.status_code == 401


def test_ingest_run_bad_key_returns_401(ingest_setup) -> None:
    client, _project, _raw_key = ingest_setup
    resp = client.post(
        "/api/v1/runs",
        json={"report": _minimal_report_dict()},
        headers={"Authorization": "Bearer tsk_totallywrongkey0000000000000000000000000000"},
    )
    assert resp.status_code == 401


def test_ingest_run_malformed_report_returns_422(ingest_setup) -> None:
    client, _project, raw_key = ingest_setup
    resp = client.post(
        "/api/v1/runs",
        json={"report": {"results": "not-a-list"}},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/runs/{run_id}
# ---------------------------------------------------------------------------


def test_get_run_returns_200_after_ingest(ingest_setup) -> None:
    client, _project, raw_key = ingest_setup
    post_resp = client.post(
        "/api/v1/runs",
        json={"report": _minimal_report_dict()},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert post_resp.status_code == 201
    run_id = post_resp.json()["run_id"]

    get_resp = client.get(
        f"/api/v1/runs/{run_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["run_id"] == run_id


def test_get_run_nonexistent_returns_404(ingest_setup) -> None:
    client, _project, raw_key = ingest_setup
    resp = client.get(
        f"/api/v1/runs/{new_id()}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 404


def test_get_run_cross_project_returns_404(ingest_setup, db_session) -> None:
    client, _project_a, raw_key_a = ingest_setup

    project_b = Project(id=new_id(), name="Project B", slug="project-b-xp")
    db_session.add(project_b)
    db_session.flush()

    run_b = Run(
        id=new_id(),
        project_id=project_b.id,
        label=None,
        status="completed",
        n_cases=0,
        pass_rate=0.0,
        mean_score=None,
        error_count=0,
        source_metadata=None,
    )
    db_session.add(run_b)
    db_session.flush()

    resp = client.get(
        f"/api/v1/runs/{run_b.id}",
        headers={"Authorization": f"Bearer {raw_key_a}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /healthz
# ---------------------------------------------------------------------------


def test_healthz_returns_ok(ingest_setup) -> None:
    client, _project, _raw_key = ingest_setup
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Gate results wired into ingest (C3)
# ---------------------------------------------------------------------------


def test_ingest_run_response_always_has_gate_results_field(ingest_setup) -> None:
    """With no gates seeded the response must still contain gate_results: []."""
    client, _project, raw_key = ingest_setup
    resp = client.post(
        "/api/v1/runs",
        json={"label": "baseline", "report": _minimal_report_dict()},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "gate_results" in data
    assert data["gate_results"] == []


def test_ingest_run_breaching_gate_returns_failed_gate_result(ingest_setup, db_session) -> None:
    """A run that breaches a seeded gate has passed=False in the 201 response gate_results."""
    client, project, raw_key = ingest_setup

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="high-bar",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.99,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    failing_report = {
        "results": [
            {
                "case": {"id": new_id(), "input": {"q": "x"}, "expected": None},
                "trace": {
                    "id": new_id(),
                    "name": "agent",
                    "input": {"q": "x"},
                    "output": {"a": "wrong"},
                    "start": 0.0,
                    "end": 0.3,
                },
                "scores": [{"scorer": "exact", "value": 0.0, "passed": False}],
            }
        ]
    }
    resp = client.post(
        "/api/v1/runs",
        json={"label": "breach-run", "report": failing_report},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["gate_results"]) == 1
    gr = data["gate_results"][0]
    assert gr["name"] == "high-bar"
    assert gr["passed"] is False
    assert gr["threshold"] == _pytest.approx(0.99)
    assert gr["actual"] == _pytest.approx(0.0)


def test_ingest_run_breach_persists_run_gate_result_row(ingest_setup, db_session) -> None:
    """After a breaching ingest a RunGateResult row must be queryable in the same session."""
    from sqlalchemy import select

    client, project, raw_key = ingest_setup

    gate = QualityGate(
        id=new_id(),
        project_id=project.id,
        name="strict-db-gate",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.99,
        enabled=True,
    )
    db_session.add(gate)
    db_session.flush()

    failing_report = {
        "results": [
            {
                "case": {"id": new_id(), "input": {"q": "y"}, "expected": None},
                "trace": {
                    "id": new_id(),
                    "name": "agent",
                    "input": {"q": "y"},
                    "output": {"a": "bad"},
                    "start": 0.0,
                    "end": 0.2,
                },
                "scores": [{"scorer": "exact", "value": 0.0, "passed": False}],
            }
        ]
    }
    resp = client.post(
        "/api/v1/runs",
        json={"label": "breach-db", "report": failing_report},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    rgr = db_session.scalar(select(RunGateResult).where(RunGateResult.run_id == run_id))
    assert rgr is not None
    assert rgr.passed is False
    assert rgr.gate_name == "strict-db-gate"


def test_ingest_run_gate_eval_exception_still_returns_201(ingest_setup, monkeypatch) -> None:
    """If evaluate_and_notify raises the endpoint must still return 201."""
    import tokensurf_server.ingest as ingest_mod

    client, _project, raw_key = ingest_setup

    def _always_crash(session, *, project, run, report):
        raise RuntimeError("pipeline totally on fire")

    monkeypatch.setattr(ingest_mod, "evaluate_and_notify", _always_crash)

    resp = client.post(
        "/api/v1/runs",
        json={"label": "crash-test", "report": _minimal_report_dict()},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 201
    assert "run_id" in resp.json()
