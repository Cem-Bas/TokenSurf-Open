"""Example: reference/embedding scorer (EmbeddingSimilarity).

Run as a library:
    from reference_scorer import main; main()
Run via the CLI:
    tokensurf eval run packages/tokensurf/examples/reference_scorer.py

Fully offline: EmbeddingSimilarity is wired to a FakeEmbeddingClient that turns
text into a deterministic bag-of-words vector, so no network call or embedding
provider key is needed.
"""

from __future__ import annotations

import tokensurf as ts
from tokensurf.eval.reporter import render_console

# Fixed vocabulary -> deterministic, tiny "embedding" (one-hot word counts).
_VOCAB = ["paris", "france", "capital", "tokyo", "japan", "sky", "blue"]


def _vectorize(text: str) -> list[float]:
    words = text.lower().split()
    return [float(words.count(w)) for w in _VOCAB]


class FakeEmbeddingClient:
    """Offline, deterministic embedding client (implements the EmbeddingClient protocol)."""

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        return [_vectorize(t) for t in texts]


def task(question: str) -> str:
    """A tiny fake agent answering in a full sentence (not an exact-match string)."""
    with ts.span("answer", type="llm", input=question):
        if "france" in question.lower():
            return "The capital of France is Paris."
        if "japan" in question.lower():
            return "The capital of Japan is Tokyo."
        return "The sky is blue."


data = ts.Dataset.from_list(
    [
        {"id": "c1", "input": "capital of France", "expected": "Paris, the capital of France"},
        {"id": "c2", "input": "capital of Japan", "expected": "Tokyo, the capital of Japan"},
        {"id": "c3", "input": "color of the sky", "expected": "The capital of France is Paris."},
    ]
)


scorers: list[ts.Scorer] = [
    # Compares the task's free-text output against case.expected by cosine
    # similarity of their (fake) embeddings, not exact string equality.
    ts.EmbeddingSimilarity(client=FakeEmbeddingClient(), threshold=0.5),
]


def main() -> ts.EvalReport:
    report = ts.evaluate(task=task, data=data, scorers=scorers)
    print(render_console(report))
    ts.assert_eval(report, min_pass_rate=0.5)
    return report


if __name__ == "__main__":
    main()
