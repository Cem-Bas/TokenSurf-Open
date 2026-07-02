from tokensurf.core.models import Case, EvalCaseResult, ScoreResult, Trace


def test_eval_case_result_defaults():
    case = Case(id="c1", input="q")
    r = EvalCaseResult(case=case)
    assert r.case == case
    assert r.trace is None
    assert r.scores == []


def test_eval_case_result_with_trace_and_scores_round_trip():
    case = Case(id="c1", input="q")
    trace = Trace(id="t1", name="run", start=0.0, end=1.0)
    scores = [ScoreResult(scorer="ExactMatch", value=1.0, passed=True)]
    r = EvalCaseResult(case=case, trace=trace, scores=scores)
    assert EvalCaseResult.model_validate_json(r.model_dump_json()) == r
