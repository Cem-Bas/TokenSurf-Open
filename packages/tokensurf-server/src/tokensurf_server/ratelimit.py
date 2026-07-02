"""In-process per-key sliding-window rate limiter (H1).

No new runtime dependencies — stdlib only (collections, math, threading, time).

Note: the limiter is per-process and resets on restart.  In multi-worker
deployments, enforce an additional rate limit at the gateway/reverse proxy.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


def parse_rate(spec: str) -> tuple[int, float]:
    """Parse "count/window_seconds" into (count, window_seconds).

    A count of 0 (or negative) signals a disabled limiter — callers treat
    this as "always allow".  Raises ValueError for any malformed spec.
    """
    parts = spec.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid rate spec {spec!r}: expected 'count/window_seconds' (e.g. '30/60')."
        )
    raw_count, raw_window = parts
    try:
        count = int(raw_count)
        window = float(raw_window)
    except ValueError as err:
        raise ValueError(
            f"Invalid rate spec {spec!r}: count must be an integer and window a number."
        ) from err
    if window <= 0:
        # A zero/negative window would make a positive count silently never block.
        raise ValueError(f"Invalid rate spec {spec!r}: window_seconds must be > 0.")
    return (count, window)


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window event counter.

    Args:
        max_events: Maximum events allowed per *window_seconds*.  0 or
            negative disables the limiter (``allow`` always returns True).
        window_seconds: Length of the sliding window in seconds.
        clock: Zero-arg callable returning a monotonic float.  Defaults to
            ``time.monotonic``; inject a fake clock in unit tests.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict(self, dq: deque[float], now: float) -> None:
        """Drop timestamps that have fallen outside the current window."""
        cutoff = now - self._window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def clear(self) -> None:
        """Forget all recorded events (used to isolate the per-process limiter in tests)."""
        with self._lock:
            self._buckets.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow(self, key: str) -> bool:
        """Return True and record the event if under the limit; False otherwise.

        When ``max_events <= 0`` (disabled) always returns True without
        recording anything.
        """
        if self._max <= 0:
            return True

        now = self._clock()
        with self._lock:
            dq = self._buckets.setdefault(key, deque())
            self._evict(dq, now)
            if len(dq) < self._max:
                dq.append(now)
                return True
            return False

    def retry_after(self, key: str) -> int:
        """Return the ceiling of seconds until the oldest in-window event expires.

        Returns 0 when the key is currently under the limit (allowed now).
        Always returns 0 when the limiter is disabled.
        """
        if self._max <= 0:
            return 0

        now = self._clock()
        with self._lock:
            dq = self._buckets.get(key)
            if dq is None:
                return 0
            self._evict(dq, now)
            if len(dq) < self._max:
                return 0
            oldest = dq[0]
            remaining = (oldest + self._window) - now
            return max(0, math.ceil(remaining))
