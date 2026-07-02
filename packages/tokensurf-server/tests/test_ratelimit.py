"""Pure-unit tests for ratelimit.py — parse_rate and SlidingWindowLimiter.

No DB, no app startup required.  A fake incrementable clock is injected
via the ``clock`` parameter to make time-sensitive assertions deterministic.
"""

from __future__ import annotations

import pytest


def _make_clock(start: float = 0.0):
    """Return (clock_fn, advance_fn) sharing a mutable tick list."""
    t = [start]

    def clock() -> float:
        return t[0]

    def advance(seconds: float) -> None:
        t[0] += seconds

    return clock, advance


class TestParseRate:
    def test_standard_30_per_60(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        count, window = parse_rate("30/60")
        assert count == 30
        assert window == 60.0

    def test_disabled_zero_count(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        count, window = parse_rate("0/60")
        assert count == 0
        assert window == 60.0

    def test_one_per_second(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        count, window = parse_rate("1/1")
        assert count == 1
        assert window == 1.0

    def test_malformed_no_slash_raises_value_error(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        with pytest.raises(ValueError):
            parse_rate("3060")

    def test_malformed_non_numeric_raises_value_error(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        with pytest.raises(ValueError):
            parse_rate("abc/def")

    def test_malformed_empty_string_raises_value_error(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        with pytest.raises(ValueError):
            parse_rate("")

    def test_malformed_extra_slash_raises_value_error(self) -> None:
        from tokensurf_server.ratelimit import parse_rate

        with pytest.raises(ValueError):
            parse_rate("1/2/3")


class TestSlidingWindowLimiter:
    def test_allows_events_up_to_max(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, _ = _make_clock()
        limiter = SlidingWindowLimiter(max_events=3, window_seconds=60.0, clock=clock)
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True

    def test_blocks_event_exceeding_max(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, _ = _make_clock()
        limiter = SlidingWindowLimiter(max_events=2, window_seconds=60.0, clock=clock)
        assert limiter.allow("k") is True
        assert limiter.allow("k") is True
        assert limiter.allow("k") is False  # third call is blocked

    def test_re_allows_after_window_expires(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, advance = _make_clock(start=0.0)
        limiter = SlidingWindowLimiter(max_events=2, window_seconds=60.0, clock=clock)
        limiter.allow("k")  # t=0
        limiter.allow("k")  # t=0
        assert limiter.allow("k") is False  # blocked at t=0
        advance(61.0)  # t=61; events at t=0 exit the 60 s window
        assert limiter.allow("k") is True  # re-allowed

    def test_disabled_limiter_always_allows(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, _ = _make_clock()
        limiter = SlidingWindowLimiter(max_events=0, window_seconds=60.0, clock=clock)
        for _ in range(200):
            assert limiter.allow("k") is True

    def test_per_key_isolation(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, _ = _make_clock()
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60.0, clock=clock)
        assert limiter.allow("proj-a") is True
        assert limiter.allow("proj-a") is False  # proj-a exhausted
        assert limiter.allow("proj-b") is True  # proj-b is independent

    def test_retry_after_returns_zero_when_under_limit(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, _ = _make_clock(start=0.0)
        limiter = SlidingWindowLimiter(max_events=5, window_seconds=60.0, clock=clock)
        assert limiter.retry_after("k") == 0

    def test_retry_after_returns_ceil_seconds_when_blocked(self) -> None:
        from tokensurf_server.ratelimit import SlidingWindowLimiter

        clock, advance = _make_clock(start=0.0)
        limiter = SlidingWindowLimiter(max_events=1, window_seconds=60.0, clock=clock)
        limiter.allow("k")  # event at t=0; expires at t=60
        advance(10.0)  # now t=10
        assert limiter.allow("k") is False
        # oldest event expires at t=60; 60 - 10 = 50 s remain → ceil(50) == 50
        assert limiter.retry_after("k") == 50


def test_parse_rate_zero_window_rejected() -> None:
    """A positive count with a non-positive window must not silently disable limiting."""
    import pytest

    from tokensurf_server.ratelimit import parse_rate

    with pytest.raises(ValueError):
        parse_rate("5/0")
    with pytest.raises(ValueError):
        parse_rate("5/-1")


def test_stale_keys_are_reclaimed():
    """The periodic sweep drops keys whose events have all expired (no unbounded growth)."""
    from tokensurf_server.ratelimit import SlidingWindowLimiter

    clock = [0.0]
    lim = SlidingWindowLimiter(1, 10, clock=lambda: clock[0])
    lim._sweep_every = 4  # sweep often so the test is fast
    for i in range(10):
        lim.allow(f"ip{i}")  # 10 distinct keys recorded at t=0
    assert len(lim._buckets) == 10

    clock[0] = 100.0  # advance well past the 10s window
    for _ in range(4):  # trigger a sweep
        lim.allow("trigger")

    assert "ip0" not in lim._buckets, "expired keys must be reclaimed"
    assert len(lim._buckets) <= 1  # only the live 'trigger' key remains
