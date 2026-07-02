"""Pure quality-gate evaluation — no DB writes, no side effects."""

from __future__ import annotations

from dataclasses import dataclass

from tokensurf import EvalReport

from tokensurf_server.models import QualityGate


@dataclass
class GateResult:
    gate_id: str | None
    name: str
    metric: str
    scorer: str | None
    comparison: str
    threshold: float
    actual: float | None
    passed: bool


_COMPARATORS: dict[str, object] = {
    "lt": lambda a, t: a < t,
    "lte": lambda a, t: a <= t,
    "gt": lambda a, t: a > t,
    "gte": lambda a, t: a >= t,
}


def _metric_value(report: EvalReport, metric: str, scorer: str | None) -> float | None:
    if metric == "pass_rate":
        return report.pass_rate()
    if metric == "mean_score":
        return report.mean_score()
    if metric == "scorer_pass_rate":
        return report.pass_rate(scorer=scorer)
    return None


def evaluate_gate(report: EvalReport, gate: QualityGate) -> GateResult:
    """Evaluate one gate against *report*. Returns a GateResult; never raises."""
    actual = _metric_value(report, gate.metric, gate.scorer)
    # actual is None (e.g. mean_score over all-errored) → not applicable → passed=True
    # (don't alert when there is no data to evaluate against)
    passed: bool
    if actual is None:
        passed = True
    else:
        comparator = _COMPARATORS[gate.comparison]
        passed = bool(comparator(actual, gate.threshold))  # type: ignore[operator]
    return GateResult(
        gate_id=gate.id,
        name=gate.name,
        metric=gate.metric,
        scorer=gate.scorer,
        comparison=gate.comparison,
        threshold=gate.threshold,
        actual=actual,
        passed=passed,
    )


def evaluate_gates(report: EvalReport, gates: list[QualityGate]) -> list[GateResult]:
    """Evaluate all *enabled* gates; disabled gates are silently skipped."""
    return [evaluate_gate(report, g) for g in gates if g.enabled]
