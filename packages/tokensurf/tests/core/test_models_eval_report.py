import pytest

from tokensurf.core.models import Case, EvalCaseResult, EvalReport, ScoreResult


def _result(*scores: ScoreResult) -> EvalCaseResult:
    return EvalCaseResult(case=Case(id="c", input="q"), scores=list(scores))


def test_empty_report_aggregations():
    report = EvalReport()
    assert report.results == []
    assert report.pass_rate() == 0.0
    assert report.mean_score() is None
    assert report.error_count() == 0
    assert report.scorer_names() == []


def test_pass_rate_excludes_errored_from_denominator():
    report = EvalReport(
        results=[
            _result(ScoreResult(scorer="EM", value=1.0, passed=True)),
            _result(ScoreResult(scorer="EM", value=0.0, passed=False)),
            _result(ScoreResult.errored("EM", "boom")),
        ]
    )
    # 1 passed out of 2 non-errored -> 0.5; the errored score is not counted.
    assert report.pass_rate() == 0.5


def test_pass_rate_per_scorer_filter():
    report = EvalReport(
        results=[
            _result(
                ScoreResult(scorer="EM", value=1.0, passed=True),
                ScoreResult(scorer="Judge", value=0.2, passed=False),
            ),
            _result(
                ScoreResult(scorer="EM", value=1.0, passed=True),
                ScoreResult(scorer="Judge", value=0.9, passed=True),
            ),
        ]
    )
    assert report.pass_rate("EM") == 1.0
    assert report.pass_rate("Judge") == 0.5


def test_mean_score_ignores_errored_none_values_and_filters_by_scorer():
    report = EvalReport(
        results=[
            _result(ScoreResult(scorer="Judge", value=0.8, passed=True)),
            _result(ScoreResult(scorer="Judge", value=0.4, passed=False)),
            _result(ScoreResult.errored("Judge", "boom")),
        ]
    )
    assert report.mean_score("Judge") == pytest.approx(0.6)
    assert report.mean_score("missing") is None


def test_error_count_and_scorer_names_sorted_unique():
    report = EvalReport(
        results=[
            _result(
                ScoreResult(scorer="EM", value=1.0, passed=True),
                ScoreResult.errored("Judge", "boom"),
            ),
            _result(ScoreResult.errored("EM", "kaboom")),
        ]
    )
    assert report.error_count() == 2
    assert report.scorer_names() == ["EM", "Judge"]


def test_pass_rate_returns_zero_when_all_errored():
    report = EvalReport(results=[_result(ScoreResult.errored("EM", "x"))])
    assert report.pass_rate() == 0.0
