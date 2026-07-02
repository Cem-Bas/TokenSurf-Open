from tokensurf.core.models import Trace
from tokensurf.scorers.deterministic import (
    Contains,
    CostUnder,
    ExactMatch,
    JSONSchemaValid,
    LatencyUnder,
    Regex,
    ToolCalled,
)


def test_exact_match_uses_case_expected(sample_trace, sample_case):
    assert ExactMatch().score(trace=sample_trace, case=sample_case).value == 1.0


def test_exact_match_explicit_expected(sample_trace):
    result = ExactMatch(expected="nope").score(trace=sample_trace)
    assert result.value == 0.0
    assert result.passed is False


def test_contains_case_insensitive(sample_trace):
    assert Contains(substring="ANSWER").score(trace=sample_trace).passed is True
    assert (
        Contains(substring="ANSWER", case_sensitive=True).score(trace=sample_trace).passed is False
    )


def test_regex(sample_trace):
    assert Regex(pattern=r"\d+").score(trace=sample_trace).value == 1.0
    assert Regex(pattern=r"zzz").score(trace=sample_trace).value == 0.0


def test_json_schema_valid():
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    }
    good = Trace(id="t", name="n", output={"name": "x", "age": 3}, start=0.0)
    bad = Trace(id="t", name="n", output={"name": "x"}, start=0.0)
    assert JSONSchemaValid(schema=schema).score(trace=good).value == 1.0
    assert JSONSchemaValid(schema=schema).score(trace=bad).value == 0.0


def test_json_schema_parses_string_output():
    trace = Trace(id="t", name="n", output='{"name": "x"}', start=0.0)
    schema = {"type": "object", "required": ["name"]}
    assert JSONSchemaValid(schema=schema).score(trace=trace).passed is True


def test_latency_under(sample_trace):
    assert LatencyUnder(seconds=2.0).score(trace=sample_trace).passed is True
    assert LatencyUnder(seconds=1.0).score(trace=sample_trace).passed is False


def test_cost_under(sample_trace):
    # span costs 0.002 + 0.001 = 0.003
    assert CostUnder(usd=0.01).score(trace=sample_trace).passed is True
    assert CostUnder(usd=0.001).score(trace=sample_trace).passed is False


def test_tool_called(sample_trace):
    assert ToolCalled(name="search").score(trace=sample_trace).passed is True
    assert ToolCalled(name="missing").score(trace=sample_trace).passed is False
