"""End-to-end smoke test for the trajectory-scorers example."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "trajectory_scorers.py"


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trajectory_scorers", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trajectory_example_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_example()
    report = mod.main()

    out = capsys.readouterr().out
    for scorer in mod.scorers:
        assert scorer.name in out

    assert len(report.results) == 2
    assert report.error_count() == 0

    # Both cases eventually return the right value via primary or fallback.
    assert report.pass_rate("ToolSequence") == pytest.approx(1.0)
    assert report.pass_rate("NoLoops") == pytest.approx(1.0)
    assert report.pass_rate("StepBudget") == pytest.approx(1.0)
    # c2's primary_lookup errors then fallback_lookup succeeds -> recovered.
    # c1 has no error span at all -> Recovery treats "no error spans" as passing too.
    assert report.pass_rate("Recovery") == pytest.approx(1.0)
    # Only c1 calls the tool named "primary_lookup" successfully as its only step;
    # c2 also calls it (it's tried first, even though it raises) -> both count.
    assert report.pass_rate("ToolCalled") == pytest.approx(1.0)


def test_trajectory_example_runs_as_a_script() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Recovery" in proc.stdout
