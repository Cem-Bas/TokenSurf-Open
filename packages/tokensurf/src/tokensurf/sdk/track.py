from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from math import isfinite
from typing import Any

from tokensurf.core.ids import new_id
from tokensurf.core.models import Span, SpanType, Trace
from tokensurf.sdk.sinks import Sink

_CURRENT: ContextVar[Trace | None] = ContextVar("tokensurf_current_trace", default=None)


def current_trace() -> Trace | None:
    return _CURRENT.get()


def track(fn=None, *, name: str | None = None, sink: Sink | None = None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if _CURRENT.get() is not None:
                # Nested @track: a Trace is already active (e.g. the runner wrapped
                # this task, or an outer @track is running). Reuse it so spans land
                # on the outer trajectory; the outermost frame owns
                # start/end/input/output/error and the sink write. Stay transparent.
                return func(*args, **kwargs)
            trace = Trace(id=new_id(), name=name or func.__name__, start=time.time())
            if args:
                trace.input = args[0]
            token = _CURRENT.set(trace)
            try:
                result = func(*args, **kwargs)
                trace.output = result
                return result
            except Exception as exc:
                trace.error = repr(exc)
                raise
            finally:
                trace.end = time.time()
                _CURRENT.reset(token)
                if sink is not None:
                    try:
                        sink.write(trace)
                    except Exception:
                        pass  # best-effort capture: never break user code

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def _call_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Keep common tool calls readable while preserving all supplied arguments."""
    if len(args) == 1 and not kwargs:
        return args[0]
    if not args:
        return dict(kwargs)
    return {"args": list(args), "kwargs": dict(kwargs)}


def tool(
    fn=None,
    *,
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
):
    """Record a function call as a tool span when it runs inside a trace."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with span(name or func.__name__, type="tool", input=_call_input(args, kwargs)) as sp:
                if attributes:
                    sp.attributes.update(attributes)
                result = func(*args, **kwargs)
                sp.output = result
                return result

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def approval(fn=None, *, for_tool: str, name: str | None = None):
    """Record whether an approval function granted a later protected tool call."""
    if not for_tool:
        raise ValueError("for_tool must not be empty")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with span(name or func.__name__, type="custom", input=_call_input(args, kwargs)) as sp:
                sp.attributes["approval_for"] = for_tool
                result = func(*args, **kwargs)
                sp.output = result
                sp.attributes["approval_granted"] = bool(result)
                return result

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


def record_payment(
    *,
    amount_usd: float | None = None,
    protocol: str = "x402",
    amount: str | int | None = None,
    asset: str | None = None,
    network: str | None = None,
    recipient: str | None = None,
    payer: str | None = None,
    success: bool = True,
    transaction: str | None = None,
) -> Span:
    """Record an agent payment without coupling TokenSurf to a payment client.

    ``amount`` is the protocol-native amount (often base units in x402). It is
    intentionally kept separate from ``amount_usd`` so unlike assets are never
    silently added together. Payment signatures and authorization headers should
    not be passed here because trace data may be displayed or exported.
    """
    if not isinstance(protocol, str) or not protocol.strip():
        raise ValueError("protocol must not be empty")
    if not isinstance(success, bool):
        raise ValueError("success must be a boolean")
    if amount_usd is not None:
        if isinstance(amount_usd, bool):
            raise ValueError("amount_usd must be a non-negative finite number")
        try:
            amount_usd = float(amount_usd)
        except (TypeError, ValueError):
            raise ValueError("amount_usd must be a non-negative finite number") from None
        if amount_usd < 0 or not isfinite(amount_usd):
            raise ValueError("amount_usd must be a non-negative finite number")

    payment = {
        "protocol": protocol.strip(),
        "amount_usd": amount_usd,
        "amount": amount,
        "asset": asset,
        "network": network,
        "recipient": recipient,
        "payer": payer,
        "success": success,
        "transaction": transaction,
    }
    attributes = {f"payment.{key}": value for key, value in payment.items() if value is not None}
    attributes["payment.recorded"] = True
    # CostUnder already understands the generic ``cost`` attribute. Only a
    # successful settlement is money spent; failed attempts remain visible but
    # do not inflate total cost.
    if success and amount_usd is not None:
        attributes["cost"] = amount_usd

    with span(f"payment.{protocol.strip()}", type="custom") as payment_span:
        payment_span.output = payment
        payment_span.attributes.update(attributes)
    return payment_span


@contextmanager
def span(name: str, *, type: SpanType = "custom", input: Any = None) -> Iterator[Span]:
    trace = _CURRENT.get()
    sp = Span(id=new_id(), type=type, name=name, input=input, start=time.time())
    if trace is not None:
        sp.parent_id = trace.id
        trace.spans.append(sp)
    try:
        yield sp
    except Exception as exc:
        sp.error = repr(exc)
        raise
    finally:
        sp.end = time.time()
