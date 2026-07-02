import pytest

from tokensurf.core.models import Trace
from tokensurf.sdk.track import current_trace, span, track


class ListSink:
    def __init__(self) -> None:
        self.traces: list[Trace] = []

    def write(self, trace: Trace) -> None:
        self.traces.append(trace)


def test_track_bare_captures_output():
    @track
    def agent(q):
        return q.upper()

    assert agent("hi") == "HI"


def test_track_parameterized_writes_trace_to_sink():
    sink = ListSink()

    @track(name="myagent", sink=sink)
    def agent(q):
        return q + "!"

    assert agent("yo") == "yo!"
    assert len(sink.traces) == 1
    t = sink.traces[0]
    assert t.name == "myagent"
    assert t.input == "yo"
    assert t.output == "yo!"
    assert t.error is None
    assert t.end is not None and t.end >= t.start


def test_current_trace_is_none_outside_track():
    assert current_trace() is None


def test_current_trace_is_set_inside_and_reset_after():
    seen: list[Trace | None] = []

    @track
    def agent(q):
        seen.append(current_trace())
        return q

    agent("x")
    assert seen[0] is not None
    assert seen[0].name == "agent"
    assert current_trace() is None


def test_span_appended_to_current_trace_with_output():
    sink = ListSink()

    @track(sink=sink)
    def agent(q):
        with span("retrieval", type="tool", input=q) as sp:
            sp.output = ["doc1", "doc2"]
        return "done"

    agent("query")
    t = sink.traces[0]
    assert len(t.spans) == 1
    s = t.spans[0]
    assert s.name == "retrieval"
    assert s.type == "tool"
    assert s.input == "query"
    assert s.output == ["doc1", "doc2"]
    assert s.parent_id == t.id
    assert s.error is None
    assert s.end is not None and s.end >= s.start


def test_span_records_error_then_reraises():
    sink = ListSink()

    @track(sink=sink)
    def agent(q):
        with span("bad", type="tool"):
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        agent("x")

    t = sink.traces[0]
    assert len(t.spans) == 1
    assert t.spans[0].error is not None
    assert "boom" in t.spans[0].error


def test_span_outside_track_is_noop_safe():
    with span("orphan", type="custom") as sp:
        sp.output = 1
    assert current_trace() is None


def test_track_records_exception_on_trace_then_reraises():
    sink = ListSink()

    @track(sink=sink)
    def agent(q):
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        agent("x")

    assert len(sink.traces) == 1
    t = sink.traces[0]
    assert t.error is not None
    assert "kaboom" in t.error
    assert t.output is None
    assert t.end is not None


def test_sink_raising_never_breaks_wrapped_function():
    class ExplodingSink:
        def write(self, trace):
            raise OSError("disk full")

    @track(sink=ExplodingSink())
    def agent(q):
        return q * 2

    # The sink blows up internally, but the user's result is returned cleanly.
    assert agent("ab") == "abab"
