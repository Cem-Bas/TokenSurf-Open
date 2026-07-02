from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import TypeVar

from tokensurf.core.models import Case, ScoreResult, Trace


class Scorer(ABC):
    name: str

    @abstractmethod
    def score(
        self, *, trace: Trace, case: Case | None = None
    ) -> ScoreResult | Awaitable[ScoreResult]: ...


REGISTRY: dict[str, type[Scorer]] = {}

S = TypeVar("S", bound=Scorer)


def register(cls: type[S]) -> type[S]:
    REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> type[Scorer]:
    return REGISTRY[name]
