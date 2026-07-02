"""TokenSurf quickstart: evaluate a tiny agent in CI with NO API key.

Run as a library:
    from quickstart_eval import main; main()
Run via the CLI:
    tokensurf eval run packages/tokensurf/examples/quickstart_eval.py

The LLM judge is wired to an in-memory FakeLLMClient, so this example needs no
network access and no provider key.
"""

from __future__ import annotations

import tokensurf as ts
from tokensurf.eval.reporter import render_console
from tokensurf.scorers.llm import LLMResponse


class FakeLLMClient:
    """Offline, deterministic LLM client (implements the LLMClient protocol).

    Always returns the same integer 1-10 score, so the judge is reproducible
    and the example runs with no API key.
    """

    def __init__(self, score: int = 8) -> None:
        self._score = score

    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse:
        return LLMResponse(text=str(self._score), model=model, cost=0.0, latency=0.0)


_ANSWERS = {
    "capital of France": "Paris",
    "capital of Japan": "Tokyo",
    "2 + 2": "5",  # deliberately wrong -> demonstrates a failing case
}


def task(question: str) -> str:
    """A tiny fake agent. The eval runner tracks it, so its tool span is
    captured on the run's trajectory (no @track needed here)."""
    with ts.span("lookup", type="tool", input=question):
        return _ANSWERS.get(question, "I don't know")


# A 3-row in-memory dataset.
data = ts.Dataset.from_list(
    [
        {"id": "c1", "input": "capital of France", "expected": "Paris"},
        {"id": "c2", "input": "capital of Japan", "expected": "Tokyo"},
        {"id": "c3", "input": "2 + 2", "expected": "4"},
    ]
)


# One deterministic scorer + one LLM judge (mocked, offline).
scorers: list[ts.Scorer] = [
    ts.ExactMatch(),
    ts.LLMJudge(criteria="answers the question correctly", client=FakeLLMClient(score=8)),
]


def main() -> ts.EvalReport:
    report = ts.evaluate(task=task, data=data, scorers=scorers)
    print(render_console(report))
    ts.assert_eval(report, min_pass_rate=0.5)
    return report


if __name__ == "__main__":
    main()
