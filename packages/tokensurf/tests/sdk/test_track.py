import pytest

from tokensurf.core.models import Trace
from tokensurf.sdk.track import approval, current_trace, record_payment, span, tool, track


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


def test_tool_decorator_records_call_and_attributes():
    sink = ListSink()

    @tool(name="docs.search", attributes={"network": False})
    def search(query, *, limit=3):
        return [query] * limit

    @track(sink=sink)
    def agent(question):
        return search(question, limit=2)

    assert agent("security") == ["security", "security"]
    recorded = sink.traces[0].spans[0]
    assert recorded.type == "tool"
    assert recorded.name == "docs.search"
    assert recorded.input == {"args": ["security"], "kwargs": {"limit": 2}}
    assert recorded.output == ["security", "security"]
    assert recorded.attributes == {"network": False}


def test_tool_decorator_records_error_then_reraises():
    sink = ListSink()

    @tool
    def explode(value):
        raise ValueError(value)

    @track(sink=sink)
    def agent(question):
        return explode(question)

    with pytest.raises(ValueError, match="bad"):
        agent("bad")

    recorded = sink.traces[0].spans[0]
    assert recorded.name == "explode"
    assert recorded.error is not None
    assert "bad" in recorded.error


def test_tool_decorator_is_transparent_outside_trace():
    @tool
    def double(value):
        return value * 2

    assert double(4) == 8
    assert current_trace() is None


def test_approval_decorator_records_grant_for_protected_tool():
    sink = ListSink()

    @approval(for_tool="send_email")
    def user_approved():
        return True

    @track(sink=sink)
    def agent(question):
        return user_approved()

    assert agent("send it") is True
    recorded = sink.traces[0].spans[0]
    assert recorded.type == "custom"
    assert recorded.name == "user_approved"
    assert recorded.output is True
    assert recorded.attributes == {
        "approval_for": "send_email",
        "approval_granted": True,
    }


def test_approval_decorator_records_denial():
    sink = ListSink()

    @approval(for_tool="delete_user", name="confirm-delete")
    def user_approved():
        return False

    @track(sink=sink)
    def agent(question):
        return user_approved()

    assert agent("delete") is False
    recorded = sink.traces[0].spans[0]
    assert recorded.name == "confirm-delete"
    assert recorded.attributes["approval_granted"] is False


def test_record_payment_captures_x402_settlement_and_generic_cost():
    sink = ListSink()

    @track(sink=sink)
    def agent():
        return record_payment(
            amount_usd=0.025,
            amount="25000",
            asset="USDC",
            network="eip155:8453",
            recipient="0xmerchant",
            payer="0xagent",
            transaction="0xtx",
        )

    recorded = agent()
    assert recorded.name == "payment.x402"
    assert recorded.type == "custom"
    assert recorded.attributes["payment.recorded"] is True
    assert recorded.attributes["payment.amount"] == "25000"
    assert recorded.attributes["payment.amount_usd"] == pytest.approx(0.025)
    assert recorded.attributes["payment.success"] is True
    assert recorded.attributes["cost"] == pytest.approx(0.025)
    assert recorded.output["network"] == "eip155:8453"
    assert sink.traces[0].spans == [recorded]


def test_failed_payment_attempt_is_visible_but_not_counted_as_cost():
    sink = ListSink()

    @track(sink=sink)
    def agent():
        return record_payment(amount_usd=1.0, recipient="merchant", success=False)

    recorded = agent()
    assert recorded.attributes["payment.success"] is False
    assert "cost" not in recorded.attributes


@pytest.mark.parametrize("amount", [-1, float("inf"), float("nan"), True, "not-a-number"])
def test_record_payment_rejects_invalid_usd_amount(amount):
    with pytest.raises(ValueError, match="amount_usd"):
        record_payment(amount_usd=amount)


def test_record_payment_outside_trace_is_safe():
    recorded = record_payment(amount="1", asset="USDC")
    assert recorded.end is not None
    assert current_trace() is None
