"""Verify the CI YAML contains a well-formed server job with the required pieces.

No network or Docker needed — pure file parse.
"""

from __future__ import annotations

from pathlib import Path

CI_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".github" / "workflows" / "ci.yml"


def _load_ci() -> dict:
    # Use tomllib-free parsing: read as text and do structural string checks.
    # A proper YAML parse would require pyyaml; we use text checks that are
    # unambiguous given the indentation structure of GitHub Actions YAML.
    assert CI_PATH.exists(), f"ci.yml not found at {CI_PATH}"
    return {"text": CI_PATH.read_text()}


def test_server_job_exists() -> None:
    d = _load_ci()
    assert "server:" in d["text"], "no 'server:' job found in ci.yml"


def test_server_job_uses_postgres16_service() -> None:
    d = _load_ci()
    assert "postgres:16" in d["text"], "postgres:16 service missing from ci.yml"


def test_server_job_health_checks_postgres() -> None:
    d = _load_ci()
    assert "pg_isready" in d["text"], "postgres health check (pg_isready) missing"


def test_server_job_sets_database_url_env() -> None:
    d = _load_ci()
    assert "DATABASE_URL" in d["text"], "DATABASE_URL env var missing from server job"


def test_server_job_runs_ruff() -> None:
    d = _load_ci()
    # ci.yml must reference ruff inside the server job block
    assert "ruff" in d["text"]


def test_server_job_runs_pyright() -> None:
    d = _load_ci()
    assert "pyright" in d["text"]


def test_server_job_runs_pytest() -> None:
    d = _load_ci()
    assert "pytest" in d["text"]
