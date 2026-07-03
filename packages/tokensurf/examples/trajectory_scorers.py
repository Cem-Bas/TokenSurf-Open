"""Example: trajectory scorers (ToolCalled, ToolSequence, NoLoops, StepBudget, Recovery).

Run as a library:
    from trajectory_scorers import main; main()
Run via the CLI:
    tokensurf eval run packages/tokensurf/examples/trajectory_scorers.py

Fully offline. The "agent" is a tiny multi-step tool-calling loop: it tries a
primary lookup tool, and on failure falls back to a secondary tool, demonstrating
recovery from a mid-run error.
"""

from __future__ import annotations

import tokensurf as ts
from tokensurf.eval.reporter import render_console

_PRIMARY = {"weather:paris": "sunny, 22C"}
_FALLBACK = {"weather:paris": "sunny, 22C", "weather:tokyo": "rainy, 18C"}


def _primary_lookup(key: str) -> str:
    if key not in _PRIMARY:
        raise KeyError(f"primary index miss: {key}")
    return _PRIMARY[key]


def _fallback_lookup(key: str) -> str:
    return _FALLBACK.get(key, "unknown")


def task(query: str) -> str:
    """Looks up `query` (e.g. "weather:tokyo"), retrying via a fallback tool on miss."""
    try:
        with ts.span("primary_lookup", type="tool", input=query) as sp:
            result = _primary_lookup(query)
            sp.output = result
            return result
    except KeyError:
        with ts.span("fallback_lookup", type="tool", input=query) as sp:
            result = _fallback_lookup(query)
            sp.output = result
            return result


data = ts.Dataset.from_list(
    [
        {"id": "c1", "input": "weather:paris", "expected": "sunny, 22C"},
        {"id": "c2", "input": "weather:tokyo", "expected": "rainy, 18C"},
    ]
)


scorers: list[ts.Scorer] = [
    # c1 only ever calls the primary tool; c2 calls primary (misses) then fallback.
    ts.ToolCalled("primary_lookup"),
    # Every case must call primary_lookup before anything else, in order.
    ts.ToolSequence(expected=["primary_lookup"]),
    # No tool is called more than twice in a row (guards against retry storms).
    ts.NoLoops(max_repeats=2),
    # No case should take more than 2 spans (primary, optionally + fallback).
    ts.StepBudget(max_steps=2),
    # c2's primary_lookup span errors, but a later span (fallback_lookup) succeeds:
    # this is exactly what Recovery checks for.
    ts.Recovery(),
]


def main() -> ts.EvalReport:
    report = ts.evaluate(task=task, data=data, scorers=scorers)
    print(render_console(report))
    ts.assert_eval(report, min_pass_rate=0.5)
    return report


if __name__ == "__main__":
    main()
