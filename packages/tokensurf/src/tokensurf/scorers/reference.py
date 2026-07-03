from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from tokensurf.core.models import Case, ScoreResult, Trace
from tokensurf.scorers.base import Scorer, register


@runtime_checkable
class EmbeddingClient(Protocol):
    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@register
class EmbeddingSimilarity(Scorer):
    name = "EmbeddingSimilarity"

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        client: EmbeddingClient | None = None,
        threshold: float = 0.8,
    ):
        self.model = model
        self.client = client
        self.threshold = threshold

    def _embed(self, texts: list[str]) -> list[list[float]]:
        embedder = getattr(self.client, "embed", None)
        if embedder is not None:
            return embedder(model=self.model, texts=texts)
        try:
            import litellm
        except ImportError as exc:  # pragma: no cover - optional 'reference' extra
            raise RuntimeError(
                "EmbeddingSimilarity needs litellm (a bundled dependency) "
                "or an injected client with an embed() method; litellm import failed"
            ) from exc
        resp = litellm.embedding(model=self.model, input=texts)
        return [item["embedding"] for item in resp["data"]]

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        reference = case.expected if case is not None else None
        if reference is None:
            return ScoreResult.errored(self.name, "no reference (case.expected) to compare against")
        try:
            vectors = self._embed([str(trace.output), str(reference)])
            sim = _cosine(vectors[0], vectors[1])
        except Exception as exc:  # noqa: BLE001 - fail-safe
            return ScoreResult.errored(self.name, f"{type(exc).__name__}: {exc}")
        value = max(0.0, min(1.0, sim))
        return ScoreResult(
            scorer=self.name,
            value=value,
            raw=sim,
            passed=value >= self.threshold,
            threshold=self.threshold,
            explanation=f"cosine similarity {sim:.3f}",
        )
