"""Pure unit tests for gates.py — no DB session required."""

from __future__ import annotations

from tokensurf import EvalReport
from tokensurf.core.ids import new_id
from tokensurf.core.models import Case, EvalCaseResult, ScoreResult

from tokensurf_server.gates import GateResult, evaluate_gate, evaluate_gates
from tokensurf_server.models import QualityGate

# ---------------------------------------------------------------------------
# In-memory helpers — no DB
# ---------------------------------------------------------------------------


def _make_gate(
    *,
    metric: str = "pass_rate",
    comparison: str = "gte",
    threshold: float = 0.8,
    scorer: str | None = None,
    enabled: bool = True,
    name: str = "my-gate",
) -> QualityGate:
    return QualityGate(
        id=new_id(),
        project_id=new_id(),
        name=name,
        metric=metric,
        scorer=scorer,
        comparison=comparison,
        threshold=threshold,
        enabled=enabled,
    )


def _report_75pct_pass() -> EvalReport:
    """3 passing + 1 failing on 'exact' scorer → pass_rate = 0.75."""
    results = []
    for _ in range(3):
        c = Case(id=new_id(), input="q", expected="a")
        results.append(
            EvalCaseResult(case=c, scores=[ScoreResult(scorer="exact", value=1.0, passed=True)])
        )
    c = Case(id=new_id(), input="q", expected="a")
    results.append(
        EvalCaseResult(case=c, scores=[ScoreResult(scorer="exact", value=0.0, passed=False)])
    )
    return EvalReport(results=results)


def _report_mean_06() -> EvalReport:
    """'quality' scorer with values 0.4, 0.6, 0.8 → mean_score = 0.6."""
    results = []
    for v in [0.4, 0.6, 0.8]:
        c = Case(id=new_id(), input="q", expected="a")
        results.append(
            EvalCaseResult(case=c, scores=[ScoreResult(scorer="quality", value=v, passed=v >= 0.5)])
        )
    return EvalReport(results=results)


def _report_multi_scorer() -> EvalReport:
    """'exact' pass_rate=0.5; 'fluency' pass_rate=1.0."""
    c1 = Case(id=new_id(), input="q", expected="a")
    c2 = Case(id=new_id(), input="q", expected="a")
    return EvalReport(
        results=[
            EvalCaseResult(
                case=c1,
                scores=[
                    ScoreResult(scorer="exact", value=1.0, passed=True),
                    ScoreResult(scorer="fluency", value=1.0, passed=True),
                ],
            ),
            EvalCaseResult(
                case=c2,
                scores=[
                    ScoreResult(scorer="exact", value=0.0, passed=False),
                    ScoreResult(scorer="fluency", value=1.0, passed=True),
                ],
            ),
        ]
    )


def _report_all_errored() -> EvalReport:
    """All scores errored → mean_score() returns None."""
    c = Case(id=new_id(), input="q", expected="a")
    return EvalReport(
        results=[
            EvalCaseResult(case=c, scores=[ScoreResult.errored(scorer="quality", error="timeout")])
        ]
    )


# ---------------------------------------------------------------------------
# GateResult dataclass
# ---------------------------------------------------------------------------


def test_gate_result_is_dataclass() -> None:
    gr = GateResult(
        gate_id="g1",
        name="accuracy",
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        actual=0.75,
        passed=False,
    )
    assert gr.gate_id == "g1"
    assert gr.name == "accuracy"
    assert gr.metric == "pass_rate"
    assert gr.scorer is None
    assert gr.comparison == "gte"
    assert gr.threshold == 0.9
    assert gr.actual == 0.75
    assert gr.passed is False


# ---------------------------------------------------------------------------
# pass_rate metric — all four comparators
# ---------------------------------------------------------------------------


def test_pass_rate_gte_passes() -> None:
    gate = _make_gate(metric="pass_rate", comparison="gte", threshold=0.7)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.actual is not None and abs(result.actual - 0.75) < 1e-9
    assert result.passed is True


def test_pass_rate_gte_fails() -> None:
    gate = _make_gate(metric="pass_rate", comparison="gte", threshold=0.8)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is False


def test_pass_rate_gt_passes() -> None:
    gate = _make_gate(metric="pass_rate", comparison="gt", threshold=0.7)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is True


def test_pass_rate_gt_fails_on_equal() -> None:
    # 0.75 > 0.75 → False
    gate = _make_gate(metric="pass_rate", comparison="gt", threshold=0.75)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is False


def test_pass_rate_lt_passes() -> None:
    gate = _make_gate(metric="pass_rate", comparison="lt", threshold=0.8)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is True


def test_pass_rate_lt_fails() -> None:
    gate = _make_gate(metric="pass_rate", comparison="lt", threshold=0.7)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is False


def test_pass_rate_lte_passes_on_equal() -> None:
    # 0.75 <= 0.75 → True (boundary)
    gate = _make_gate(metric="pass_rate", comparison="lte", threshold=0.75)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is True


def test_pass_rate_lte_fails() -> None:
    gate = _make_gate(metric="pass_rate", comparison="lte", threshold=0.74)
    result = evaluate_gate(_report_75pct_pass(), gate)
    assert result.passed is False


# ---------------------------------------------------------------------------
# mean_score metric
# ---------------------------------------------------------------------------


def test_mean_score_gte_passes() -> None:
    gate = _make_gate(metric="mean_score", comparison="gte", threshold=0.5)
    result = evaluate_gate(_report_mean_06(), gate)
    assert result.actual is not None and abs(result.actual - 0.6) < 1e-9
    assert result.passed is True


def test_mean_score_gte_fails() -> None:
    gate = _make_gate(metric="mean_score", comparison="gte", threshold=0.7)
    result = evaluate_gate(_report_mean_06(), gate)
    assert result.passed is False


# ---------------------------------------------------------------------------
# scorer_pass_rate metric — scorer filter
# ---------------------------------------------------------------------------


def test_scorer_pass_rate_uses_fluency_scorer() -> None:
    # fluency pass_rate = 1.0; gate threshold 0.9 gte → True
    gate = _make_gate(metric="scorer_pass_rate", comparison="gte", threshold=0.9, scorer="fluency")
    result = evaluate_gate(_report_multi_scorer(), gate)
    assert result.actual is not None and abs(result.actual - 1.0) < 1e-9
    assert result.passed is True


def test_scorer_pass_rate_uses_exact_scorer() -> None:
    # exact pass_rate = 0.5; gate threshold 0.9 gte → False
    gate = _make_gate(metric="scorer_pass_rate", comparison="gte", threshold=0.9, scorer="exact")
    result = evaluate_gate(_report_multi_scorer(), gate)
    assert result.actual is not None and abs(result.actual - 0.5) < 1e-9
    assert result.passed is False


def test_gate_result_preserves_scorer_name() -> None:
    gate = _make_gate(metric="scorer_pass_rate", comparison="gte", threshold=0.5, scorer="fluency")
    result = evaluate_gate(_report_multi_scorer(), gate)
    assert result.scorer == "fluency"


# ---------------------------------------------------------------------------
# None actual → passed=True (don't alert on missing data)
# ---------------------------------------------------------------------------


def test_none_actual_mean_score_passes_always() -> None:
    # All scores errored → mean_score() = None → gate should pass (not applicable)
    gate = _make_gate(metric="mean_score", comparison="gte", threshold=0.9)
    result = evaluate_gate(_report_all_errored(), gate)
    assert result.actual is None
    assert result.passed is True


# ---------------------------------------------------------------------------
# evaluate_gates — disabled gate skipped; multiple gates
# ---------------------------------------------------------------------------


def test_evaluate_gates_skips_disabled() -> None:
    disabled = _make_gate(
        metric="pass_rate", comparison="gte", threshold=0.9, enabled=False, name="skip-me"
    )
    results = evaluate_gates(_report_75pct_pass(), [disabled])
    assert results == []


def test_evaluate_gates_multiple_only_enabled() -> None:
    enabled_pass = _make_gate(
        metric="pass_rate", comparison="gte", threshold=0.7, enabled=True, name="pass-gate"
    )
    enabled_fail = _make_gate(
        metric="pass_rate", comparison="gte", threshold=0.9, enabled=True, name="fail-gate"
    )
    disabled = _make_gate(
        metric="pass_rate", comparison="gte", threshold=0.5, enabled=False, name="skip-gate"
    )

    results = evaluate_gates(_report_75pct_pass(), [enabled_pass, enabled_fail, disabled])

    assert len(results) == 2
    names = {r.name for r in results}
    assert names == {"pass-gate", "fail-gate"}
    assert next(r for r in results if r.name == "pass-gate").passed is True
    assert next(r for r in results if r.name == "fail-gate").passed is False


def test_evaluate_gates_empty_list_returns_empty() -> None:
    assert evaluate_gates(_report_75pct_pass(), []) == []
