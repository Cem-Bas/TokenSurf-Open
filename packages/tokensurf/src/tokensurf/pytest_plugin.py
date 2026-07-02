"""Pytest helpers for asserting on EvalReports."""

from __future__ import annotations

from tokensurf.core.models import EvalReport
from tokensurf.eval.reporter import render_console


def assert_eval(
    report: EvalReport,
    *,
    min_pass_rate: float,
    scorer: str | None = None,
) -> None:
    """Raise AssertionError (with a readable summary) if pass-rate is too low."""
    actual = report.pass_rate(scorer)
    if actual < min_pass_rate:
        target = scorer or "overall"
        summary = (
            f"Eval failed for '{target}': "
            f"pass_rate {actual:.3f} < required {min_pass_rate:.3f}\n"
            f"{render_console(report)}"
        )
        raise AssertionError(summary)
