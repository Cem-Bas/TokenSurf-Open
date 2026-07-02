"""End-to-end smoke test for the quickstart example (no network, mocked judge)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "quickstart_eval.py"


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quickstart_eval", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quickstart_runs_end_to_end_without_network(capsys: pytest.CaptureFixture[str]) -> None:
    qe = _load_example()

    # main() runs evaluate + render_console + assert_eval and returns the report.
    report = qe.main()

    out = capsys.readouterr().out
    # render_console printed a per-scorer table naming both scorers.
    assert qe.scorers[0].name in out
    assert qe.scorers[1].name in out

    # Non-empty report: one result per dataset row, fully offline => zero errors.
    assert len(report.results) == 3
    assert report.error_count() == 0

    # Both scorers ran for every case.
    names = report.scorer_names()
    assert qe.scorers[0].name in names
    assert qe.scorers[1].name in names

    # Deterministic, sensible pass rates: ExactMatch passes 2 of 3 rows.
    exact_name = qe.scorers[0].name
    assert report.pass_rate(exact_name) == pytest.approx(2 / 3)
    assert 0.0 < report.pass_rate() <= 1.0

    # Every case produced a captured trace with an output (used by ExactMatch).
    for result in report.results:
        assert result.trace is not None
        assert result.trace.output is not None


def test_quickstart_runs_as_a_script() -> None:
    """Running the example as a script (the CI path) succeeds and prints a report."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    # The __main__ guard must actually run main() and print the rendered table.
    assert proc.stdout.strip() != ""
    assert "ExactMatch" in proc.stdout
