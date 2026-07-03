"""Tests for `tokensurf init`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from tokensurf.cli import app

runner = CliRunner()


def test_init_creates_expected_files(tmp_path: Path) -> None:
    target = tmp_path / "myproj"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "evals" / "example_deterministic.py").exists()
    assert (target / "evals" / "example_llm_judge.py").exists()
    assert (target / "evals" / "test_agent_quality.py").exists()
    assert (target / "README.md").exists()


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "myproj"
    runner.invoke(app, ["init", str(target)])
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "myproj"
    runner.invoke(app, ["init", str(target)])
    result = runner.invoke(app, ["init", str(target), "--force"])
    assert result.exit_code == 0, result.output


def test_init_generated_eval_actually_runs(tmp_path: Path) -> None:
    target = tmp_path / "myproj"
    runner.invoke(app, ["init", str(target)])
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tokensurf.cli",
            "eval",
            "run",
            str(target / "evals" / "example_deterministic.py"),
            "--output",
            str(target / "results.jsonl"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(target),
    )
    assert proc.returncode == 0, proc.stderr
    assert "ExactMatch" in proc.stdout
    assert (target / "results.jsonl").exists()
