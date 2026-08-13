"""Deterministic payment and budget invariants over an agent trace."""

from __future__ import annotations

from collections.abc import Collection
from math import isfinite

from tokensurf.core.models import Case, ScoreResult, Span, Trace
from tokensurf.scorers.base import Scorer, register


def _payments(trace: Trace) -> list[Span]:
    return [span for span in trace.spans if span.attributes.get("payment.recorded") is True]


def _settled(trace: Trace) -> list[Span]:
    return [span for span in _payments(trace) if span.attributes.get("payment.success") is True]


def _non_negative_finite(value: float, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative finite number")
    result = float(value)
    if result < 0 or not isfinite(result):
        raise ValueError(f"{label} must be a non-negative finite number")
    return result


@register
class PaymentCostUnder(Scorer):
    """Fail when successful, explicitly USD-priced payments exceed a budget."""

    name = "PaymentCostUnder"

    def __init__(self, usd: float):
        self.usd = _non_negative_finite(usd, label="usd")

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        payments = _settled(trace)
        amounts: list[float] = []
        unpriced = 0
        for payment in payments:
            value = payment.attributes.get("payment.amount_usd")
            try:
                if value is None or isinstance(value, bool):
                    raise TypeError
                amount = float(value)
                if amount < 0 or not isfinite(amount):
                    raise ValueError
                amounts.append(amount)
            except (TypeError, ValueError):
                unpriced += 1

        raw = {
            "total_usd": sum(amounts),
            "limit_usd": self.usd,
            "settled_payments": len(payments),
            "unpriced_payments": unpriced,
        }
        if unpriced:
            return ScoreResult(
                scorer=self.name,
                value=None,
                passed=None,
                error=f"{unpriced} settled payment(s) have no valid payment.amount_usd",
                raw=raw,
            )

        total = sum(amounts)
        ok = total < self.usd
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            threshold=self.usd,
            cost=total,
            raw=raw,
            explanation=(
                None if ok else f"settled payment cost ${total:.6f} is not under ${self.usd:.6f}"
            ),
        )


@register
class PaymentCountAtMost(Scorer):
    """Fail when an agent settles more than the allowed number of payments."""

    name = "PaymentCountAtMost"

    def __init__(self, max_payments: int):
        if isinstance(max_payments, bool) or not isinstance(max_payments, int) or max_payments < 0:
            raise ValueError("max_payments must be a non-negative integer")
        self.max_payments = max_payments

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        count = len(_settled(trace))
        ok = count <= self.max_payments
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            raw={"settled_payments": count, "max_payments": self.max_payments},
            explanation=None if ok else f"settled {count} payments; maximum is {self.max_payments}",
        )


@register
class PaymentRecipientsAllowed(Scorer):
    """Fail when any attempted payment targets a recipient outside an allowlist."""

    name = "PaymentRecipientsAllowed"

    def __init__(self, recipients: str | Collection[str]):
        allowed = {recipients} if isinstance(recipients, str) else set(recipients)
        if not allowed or not all(isinstance(item, str) and item for item in allowed):
            raise ValueError("recipients must contain only non-empty strings")
        self.recipients = allowed

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        violations: list[str] = []
        for payment in _payments(trace):
            recipient = payment.attributes.get("payment.recipient")
            if not isinstance(recipient, str) or recipient not in self.recipients:
                violations.append(recipient if isinstance(recipient, str) else "<missing>")
        ok = not violations
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            raw={"disallowed_recipients": violations},
            explanation=None if ok else f"payment recipient not allowed: {', '.join(violations)}",
        )
