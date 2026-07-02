import json

from tokensurf.core.models import Case, EvalCaseResult, EvalReport, ScoreResult, Trace
from tokensurf.eval.reporter import render_console, write_jsonl


def _report():
    case1 = Case(id="c1", input="a")
    case2 = Case(id="c2", input="b")
    trace1 = Trace(id="t1", name="task", start=0.0, end=1.0)
    trace2 = Trace(id="t2", name="task", start=0.0, end=1.0)
    r1 = EvalCaseResult(
        case=case1,
        trace=trace1,
        scores=[
            ScoreResult(scorer="exact", value=1.0, passed=True),
            ScoreResult(scorer="judge", value=0.8, passed=True),
        ],
    )
    r2 = EvalCaseResult(
        case=case2,
        trace=trace2,
        scores=[
            ScoreResult(scorer="exact", value=0.0, passed=False),
            ScoreResult.errored("judge", "boom"),
        ],
    )
    return EvalReport(results=[r1, r2])


def test_render_console_contains_scorers_and_metrics():
    out = render_console(_report())
    assert "exact" in out
    assert "judge" in out
    # exact: 1 pass of 2 non-errored -> 0.500
    assert "0.500" in out
    # header labels present
    assert "pass_rate" in out
    assert "errors" in out
    # one judge error counted overall
    assert "Total errors: 1" in out


def test_write_jsonl_roundtrips(tmp_path):
    path = tmp_path / "out" / "results.jsonl"
    write_jsonl(_report(), path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["case"]["id"] == "c1"
    assert first["scores"][0]["scorer"] == "exact"
    assert first["scores"][0]["value"] == 1.0
    second = json.loads(lines[1])
    assert second["scores"][1]["error"] == "boom"
