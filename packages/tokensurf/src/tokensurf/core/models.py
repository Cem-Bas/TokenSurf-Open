"""Core pydantic v2 data models: the shared contract every component speaks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SpanType = Literal["llm", "tool", "agent", "custom"]


class Span(BaseModel):
    """One step in an agent run (an LLM call, tool call, sub-agent, etc.)."""

    id: str
    parent_id: str | None = None
    type: SpanType = "custom"
    name: str
    input: Any = None
    output: Any = None
    start: float
    end: float | None = None
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    """One full agent run: ordered spans plus top-level input/output/timing."""

    id: str
    name: str
    input: Any = None
    output: Any = None
    spans: list[Span] = Field(default_factory=list)
    start: float
    end: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration(self) -> float | None:
        """Wall-clock seconds, or ``None`` if the run has not ended."""
        if self.end is None:
            return None
        return self.end - self.start

    def spans_of(self, type: SpanType) -> list[Span]:
        """Return spans of the given ``type`` in their original order."""
        return [s for s in self.spans if s.type == type]


class Case(BaseModel):
    """One eval input with an optional reference ``expected`` value."""

    id: str
    input: Any
    expected: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoreResult(BaseModel):
    """A single scorer's verdict; ``value`` is normalized 0.0..1.0 or None."""

    scorer: str
    value: float | None
    raw: Any = None
    passed: bool | None = None
    threshold: float | None = None
    explanation: str | None = None
    error: str | None = None
    cost: float | None = None
    latency: float | None = None
    judge_model: str | None = None

    @classmethod
    def errored(cls, scorer: str, error: str) -> ScoreResult:
        """Build an errored result (no value, no pass/fail verdict)."""
        return cls(scorer=scorer, value=None, passed=None, error=error)


class EvalCaseResult(BaseModel):
    """A single case's outcome: its trace and the scores computed over it."""

    case: Case
    trace: Trace | None = None
    scores: list[ScoreResult] = Field(default_factory=list)


class EvalReport(BaseModel):
    """Aggregation over per-case results. All aggregates are computed, not stored."""

    results: list[EvalCaseResult] = Field(default_factory=list)

    def _all_scores(self, scorer: str | None = None) -> list[ScoreResult]:
        scores: list[ScoreResult] = []
        for result in self.results:
            for score in result.scores:
                if scorer is None or score.scorer == scorer:
                    scores.append(score)
        return scores

    def pass_rate(self, scorer: str | None = None) -> float:
        """Fraction of non-errored scores whose ``passed`` is True."""
        non_errored = [s for s in self._all_scores(scorer) if s.error is None]
        if not non_errored:
            return 0.0
        passed = sum(1 for s in non_errored if s.passed)
        return passed / len(non_errored)

    def mean_score(self, scorer: str | None = None) -> float | None:
        """Mean ``value`` over scores that produced a numeric value."""
        values = [s.value for s in self._all_scores(scorer) if s.value is not None]
        if not values:
            return None
        return sum(values) / len(values)

    def error_count(self) -> int:
        """Number of scores that errored across all cases."""
        return sum(1 for s in self._all_scores() if s.error is not None)

    def scorer_names(self) -> list[str]:
        """Sorted, de-duplicated list of scorer names seen in the report."""
        return sorted({s.scorer for s in self._all_scores()})
