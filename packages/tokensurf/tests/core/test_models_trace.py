from tokensurf.core.models import Span, SpanType, Trace


def _span(id: str, type: SpanType = "custom", start: float = 0.0, end: float | None = None) -> Span:
    return Span(id=id, name=id, type=type, start=start, end=end)


def test_trace_minimal_defaults():
    t = Trace(id="t1", name="run", start=0.0)
    assert t.spans == []
    assert t.input is None
    assert t.output is None
    assert t.end is None
    assert t.error is None
    assert t.metadata == {}


def test_trace_duration_is_none_without_end():
    t = Trace(id="t1", name="run", start=10.0)
    assert t.duration is None


def test_trace_duration_is_end_minus_start():
    t = Trace(id="t1", name="run", start=10.0, end=12.5)
    assert t.duration == 2.5


def test_trace_spans_of_filters_by_type_in_order():
    spans = [_span("a", "tool"), _span("b", "llm"), _span("c", "tool")]
    t = Trace(id="t1", name="run", start=0.0, spans=spans)
    assert [s.id for s in t.spans_of("tool")] == ["a", "c"]
    assert t.spans_of("agent") == []


def test_trace_round_trip_json():
    t = Trace(
        id="t1",
        name="run",
        input="q",
        output="a",
        start=0.0,
        end=1.0,
        spans=[_span("a", "tool", 0.0, 0.5)],
        metadata={"k": "v"},
    )
    assert Trace.model_validate_json(t.model_dump_json()) == t


def test_trace_metadata_default_is_not_shared_between_instances():
    a = Trace(id="a", name="a", start=0.0)
    b = Trace(id="b", name="b", start=0.0)
    a.metadata["x"] = 1
    assert b.metadata == {}
