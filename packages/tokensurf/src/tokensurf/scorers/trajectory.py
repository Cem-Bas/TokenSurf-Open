from __future__ import annotations

from tokensurf.core.models import Case, ScoreResult, Trace
from tokensurf.scorers.base import Scorer, register
from tokensurf.scorers.llm import LLMJudge


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(item in it for item in needle)


def _trajectory_summary(trace: Trace) -> str:
    """Serialize full span trajectory for the LLM judge (addendum #7)."""
    lines: list[str] = []
    for s in trace.spans:
        fields = [f"name={s.name!r}", f"type={s.type!r}"]
        if s.input is not None:
            fields.append(f"input={s.input!r}")
        if s.output is not None:
            fields.append(f"output={s.output!r}")
        if s.error is not None:
            fields.append(f"error={s.error!r}")
        lines.append("  - " + ", ".join(fields))
    return "\n".join(lines) if lines else "  (no spans)"


@register
class ToolSequence(Scorer):
    name = "ToolSequence"

    def __init__(self, expected: list[str], strict: bool = False):
        self.expected = expected
        self.strict = strict

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        actual = [s.name for s in trace.spans if s.type == "tool"]
        ok = actual == self.expected if self.strict else _is_subsequence(self.expected, actual)
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            explanation=None if ok else f"tools {actual} vs expected {self.expected}",
        )


@register
class NoLoops(Scorer):
    name = "NoLoops"

    def __init__(self, max_repeats: int = 2):
        self.max_repeats = max_repeats

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        tools = [s.name for s in trace.spans if s.type == "tool"]
        run = 0
        worst = 0
        prev: str | None = None
        for name in tools:
            run = run + 1 if name == prev else 1
            prev = name
            worst = max(worst, run)
        ok = worst <= self.max_repeats
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            explanation=None if ok else f"max consecutive repeats {worst} > {self.max_repeats}",
        )


@register
class StepBudget(Scorer):
    name = "StepBudget"

    def __init__(self, max_steps: int):
        self.max_steps = max_steps

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        steps = len(trace.spans)
        ok = steps <= self.max_steps
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            explanation=f"{steps} steps (budget {self.max_steps})",
        )


@register
class TaskCompletion(Scorer):
    name = "TaskCompletion"

    def __init__(self, judge: LLMJudge | None = None, threshold: float = 0.7):
        self.threshold = threshold
        self.judge = judge or LLMJudge(
            criteria="task completion: did the agent fully accomplish the user's task?",
            threshold=threshold,
        )

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        # Addendum #7: serialize full span trajectory into the judge input
        trajectory = _trajectory_summary(trace)
        judge_trace = trace.model_copy(
            update={"output": f"Trajectory:\n{trajectory}\n\nFinal output: {trace.output}"}
        )
        result = self.judge.score(trace=judge_trace, case=case)
        return ScoreResult(
            scorer=self.name,
            value=result.value,
            raw=result.raw,
            passed=result.passed,
            threshold=result.threshold,
            cost=result.cost,
            latency=result.latency,
            judge_model=result.judge_model,
            explanation=result.explanation,
            error=result.error,
        )


@register
class Recovery(Scorer):
    name = "Recovery"

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        spans = trace.spans
        error_idx = [i for i, s in enumerate(spans) if s.error]
        if not error_idx:
            return ScoreResult(
                scorer=self.name, value=1.0, passed=True, explanation="no error spans"
            )
        first_error = error_idx[0]
        recovered = any(s.error is None for s in spans[first_error + 1 :])
        return ScoreResult(
            scorer=self.name,
            value=1.0 if recovered else 0.0,
            passed=recovered,
            explanation="recovered after error" if recovered else "no successful span after error",
        )
