"""Eval runner: run a task over a Dataset under tracking and apply scorers."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from tokensurf.core.models import (
    Case,
    EvalCaseResult,
    EvalReport,
    ScoreResult,
    Trace,
)
from tokensurf.eval.dataset import Dataset
from tokensurf.scorers.base import Scorer
from tokensurf.sdk.sinks import Sink
from tokensurf.sdk.track import track


class _CaptureSink:
    """Best-effort sink that keeps the most recently written Trace."""

    def __init__(self) -> None:
        self.trace: Trace | None = None

    def write(self, trace: Trace) -> None:
        self.trace = trace


def _run_scorer(scorer: Scorer, trace: Trace, case: Case | None) -> ScoreResult:
    try:
        result = scorer.score(trace=trace, case=case)
        if inspect.iscoroutine(result):
            return asyncio.run(result)
        # Not a coroutine: a sync scorer returns its ScoreResult directly.
        assert isinstance(result, ScoreResult)
        return result
    except Exception as exc:  # fail-safe: a scorer never crashes the run
        name = getattr(scorer, "name", scorer.__class__.__name__)
        return ScoreResult.errored(name, str(exc))


def evaluate(
    *,
    task: Callable[[Any], Any],
    data: Dataset,
    scorers: list[Scorer],
    sink: Sink | None = None,
) -> EvalReport:
    results: list[EvalCaseResult] = []
    for case in data:
        capture = _CaptureSink()
        tracked = track(task, name=getattr(task, "__name__", "task"), sink=capture)
        try:
            tracked(case.input)
        except Exception:
            # the task error is recorded on the captured Trace; never abort the run
            pass
        trace = capture.trace
        assert trace is not None  # track() always produces a Trace
        if sink is not None:
            try:
                sink.write(trace)
            except Exception:
                pass
        scores = [_run_scorer(scorer, trace, case) for scorer in scorers]
        results.append(EvalCaseResult(case=case, trace=trace, scores=scores))
    return EvalReport(results=results)
