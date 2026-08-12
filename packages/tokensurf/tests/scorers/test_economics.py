import pytest

import tokensurf as ts
from tokensurf.core.models import Span, Trace
from tokensurf.scorers.economics import (
    PaymentCostUnder,
    PaymentCountAtMost,
    PaymentRecipientsAllowed,
)


def _payment(
    name: str,
    *,
    usd=None,
    recipient: str | None = "merchant",
    success=True,
    recorded=True,
) -> Span:
    attributes = {
        "payment.recorded": recorded,
        "payment.success": success,
        "payment.recipient": recipient,
    }
    if usd is not None:
        attributes["payment.amount_usd"] = usd
    return Span(id=name, name=name, start=0.0, end=1.0, attributes=attributes)


def _trace(spans: list[Span]) -> Trace:
    return Trace(id="trace", name="agent", start=0.0, end=1.0, spans=spans)


def test_payment_cost_under_counts_only_successful_payments():
    result = PaymentCostUnder(usd=1.0).score(
        trace=_trace([_payment("one", usd=0.25), _payment("failed", usd=100, success=False)])
    )
    assert result.passed is True
    assert result.cost == pytest.approx(0.25)
    assert result.raw == {
        "total_usd": 0.25,
        "limit_usd": 1.0,
        "settled_payments": 1,
        "unpriced_payments": 0,
    }


def test_payment_cost_under_fails_at_budget_boundary():
    result = PaymentCostUnder(usd=0.25).score(trace=_trace([_payment("one", usd=0.25)]))
    assert result.passed is False
    assert result.value == 0.0


def test_payment_cost_under_errors_instead_of_silently_ignoring_unpriced_settlement():
    result = PaymentCostUnder(usd=1.0).score(trace=_trace([_payment("native-only")]))
    assert result.passed is None
    assert result.value is None
    assert result.error == "1 settled payment(s) have no valid payment.amount_usd"
    assert result.raw["unpriced_payments"] == 1


def test_payment_count_at_most_uses_inclusive_limit():
    trace = _trace([_payment("one", usd=0.1), _payment("two", usd=0.1)])
    assert PaymentCountAtMost(2).score(trace=trace).passed is True
    assert PaymentCountAtMost(1).score(trace=trace).passed is False


def test_payment_recipients_allowed_checks_attempts_and_missing_recipient():
    trace = _trace(
        [
            _payment("ok", recipient="shop"),
            _payment("failed", recipient="unknown", success=False),
            _payment("missing", recipient=None),
        ]
    )
    result = PaymentRecipientsAllowed("shop").score(trace=trace)
    assert result.passed is False
    assert result.raw == {"disallowed_recipients": ["unknown", "<missing>"]}


def test_economics_scorers_ignore_unmarked_spans():
    trace = _trace([_payment("not-a-payment", usd=100, recipient="bad", recorded=False)])
    assert PaymentCostUnder(1).score(trace=trace).passed is True
    assert PaymentCountAtMost(0).score(trace=trace).passed is True
    assert PaymentRecipientsAllowed("good").score(trace=trace).passed is True


def test_economics_scorers_validate_configuration():
    with pytest.raises(ValueError, match="usd"):
        PaymentCostUnder(-1)
    with pytest.raises(ValueError, match="max_payments"):
        PaymentCountAtMost(-1)
    with pytest.raises(ValueError, match="recipients"):
        PaymentRecipientsAllowed([])


def test_payment_capture_and_economics_scorers_work_through_evaluate():
    def agent(request: dict) -> str:
        ts.record_payment(
            amount="25000",
            amount_usd=request["usd"],
            recipient=request["recipient"],
            success=True,
        )
        return "paid"

    report = ts.evaluate(
        task=agent,
        data=ts.Dataset.from_list(
            [{"id": "payment", "input": {"usd": 0.025, "recipient": "merchant"}}]
        ),
        scorers=[
            ts.PaymentCostUnder(0.10),
            ts.PaymentCountAtMost(1),
            ts.PaymentRecipientsAllowed("merchant"),
            ts.CostUnder(0.10),
        ],
    )

    assert [score.passed for score in report.results[0].scores] == [True, True, True, True]
    assert report.results[0].trace is not None
    assert report.results[0].trace.spans[0].name == "payment.x402"
