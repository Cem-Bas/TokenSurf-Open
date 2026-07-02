"""Verify ops files exist and contain the required structure.

These are file-system smoke tests; they require no database or Docker daemon.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # …/TokenSurf/
SERVER_PKG = REPO_ROOT / "packages" / "tokensurf-server"


def test_docker_compose_exists() -> None:
    assert (REPO_ROOT / "docker-compose.yml").exists(), "docker-compose.yml missing"


def test_docker_compose_references_postgres16() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "postgres:16" in text


def test_docker_compose_has_db_and_app_services() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "db:" in text
    assert "app:" in text


def test_docker_compose_wires_database_url() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "DATABASE_URL" in text


def test_docker_compose_exposes_port_8000() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "8000" in text


def test_docker_compose_has_change_me_comment() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    # Must remind operators to rotate placeholder creds
    assert "change" in text.lower()


def test_env_example_exists() -> None:
    assert (SERVER_PKG / ".env.example").exists(), ".env.example missing"


def test_env_example_has_required_keys() -> None:
    text = (SERVER_PKG / ".env.example").read_text()
    for key in ("DATABASE_URL", "HOST", "PORT"):
        assert key in text, f"{key} missing from .env.example"


def test_env_example_contains_no_real_secrets() -> None:
    text = (SERVER_PKG / ".env.example").read_text()
    # Placeholder value must be obviously fake — "changeme" is the convention
    assert "changeme" in text


def test_gitignore_blocks_dotenv() -> None:
    gitignore = SERVER_PKG / ".gitignore"
    assert gitignore.exists(), ".gitignore missing"
    lines = [ln.strip() for ln in gitignore.read_text().splitlines()]
    assert any(ln in {".env", ".env*", "*.env"} for ln in lines), ".env not covered by .gitignore"
