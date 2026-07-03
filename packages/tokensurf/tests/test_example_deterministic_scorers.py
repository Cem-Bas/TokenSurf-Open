"""End-to-end smoke test for the deterministic-scorers example."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "deterministic_scorers.py"


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deterministic_scorers", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_example_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_example()
    report = mod.main()

    out = capsys.readouterr().out
    for scorer in mod.scorers:
        assert scorer.name in out

    assert len(report.results) == 3
    assert report.error_count() == 0

    # c1, c2 match exactly; c3 has a different order id but ExactMatch still
    # matches because the "not_found" shape is identical -> all 3 pass ExactMatch.
    assert report.pass_rate("ExactMatch") == pytest.approx(1.0)
    # Contains("shipped") only true for o1 (c1); o2 is pending, o4 is not_found.
    assert report.pass_rate("Contains") == pytest.approx(1 / 3)
    assert report.pass_rate("Regex") == pytest.approx(1.0)
    assert report.pass_rate("JSONSchemaValid") == pytest.approx(1.0)


def test_deterministic_example_runs_as_a_script() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ExactMatch" in proc.stdout
