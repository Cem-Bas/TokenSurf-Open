from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ci_workflow_runs_the_full_gate():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for token in ["uv sync", "ruff check", "pyright", "pytest", "--cov"]:
        assert token in ci, f"CI must run: {token}"


def test_reserved_dirs_exist():
    assert (ROOT / "apps" / ".gitkeep").is_file()
    assert (ROOT / "e2e" / ".gitkeep").is_file()
