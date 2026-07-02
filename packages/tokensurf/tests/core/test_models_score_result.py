import pytest
from pydantic import ValidationError

from tokensurf.core.models import ScoreResult


def test_score_result_minimal_required_fields_and_defaults():
    r = ScoreResult(scorer="ExactMatch", value=1.0)
    assert r.scorer == "ExactMatch"
    assert r.value == 1.0
    assert r.raw is None
    assert r.passed is None
    assert r.threshold is None
    assert r.explanation is None
    assert r.error is None
    assert r.cost is None
    assert r.latency is None
    assert r.judge_model is None


def test_score_result_requires_scorer_and_value():
    with pytest.raises(ValidationError):
        ScoreResult.model_validate({"scorer": "x"})


def test_score_result_value_may_be_explicit_none():
    r = ScoreResult(scorer="x", value=None)
    assert r.value is None


def test_score_result_errored_classmethod_sets_none_value_and_passed():
    r = ScoreResult.errored("LLMJudge", "boom")
    assert r.scorer == "LLMJudge"
    assert r.value is None
    assert r.passed is None
    assert r.error == "boom"


def test_score_result_round_trip_json():
    r = ScoreResult(
        scorer="LLMJudge",
        value=0.8,
        raw=8,
        passed=True,
        threshold=0.7,
        explanation="good",
        cost=0.001,
        latency=0.2,
        judge_model="gpt-4o-mini",
    )
    assert ScoreResult.model_validate_json(r.model_dump_json()) == r
