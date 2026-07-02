import pytest

from tokensurf.core.models import Case, EvalCaseResult, EvalReport, ScoreResult
from tokensurf.pytest_plugin import assert_eval


def _report(passed_flags):
    results = []
    for i, flag in enumerate(passed_flags):
        results.append(
            EvalCaseResult(
                case=Case(id=f"c{i}", input="x"),
                scores=[ScoreResult(scorer="exact", value=1.0 if flag else 0.0, passed=flag)],
            )
        )
    return EvalReport(results=results)


def test_assert_eval_passes_when_above_threshold():
    report = _report([True, True, True, False])  # 0.75
    assert_eval(report, min_pass_rate=0.7)  # must not raise


def test_assert_eval_raises_with_summary_when_below_threshold():
    report = _report([True, False, False, False])  # 0.25
    with pytest.raises(AssertionError) as excinfo:
        assert_eval(report, min_pass_rate=0.7)
    msg = str(excinfo.value)
    assert "0.250" in msg
    assert "0.700" in msg
    assert "exact" in msg  # render_console table included


def test_assert_eval_scoped_to_named_scorer():
    results = [
        EvalCaseResult(
            case=Case(id="c0", input="x"),
            scores=[
                ScoreResult(scorer="exact", value=1.0, passed=True),
                ScoreResult(scorer="judge", value=0.0, passed=False),
            ],
        )
    ]
    report = EvalReport(results=results)
    assert_eval(report, min_pass_rate=1.0, scorer="exact")  # exact passes
    with pytest.raises(AssertionError) as excinfo:
        assert_eval(report, min_pass_rate=1.0, scorer="judge")
    assert "judge" in str(excinfo.value)
