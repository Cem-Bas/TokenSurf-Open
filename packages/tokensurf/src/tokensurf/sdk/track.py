from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
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
