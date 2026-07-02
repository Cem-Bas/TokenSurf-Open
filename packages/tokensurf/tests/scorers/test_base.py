import pytest

from tokensurf.core.models import Case, ScoreResult, Trace
from tokensurf.scorers.base import REGISTRY, Scorer, get, register


def test_scorer_is_abstract():
    with pytest.raises(TypeError):
        Scorer()  # type: ignore[abstract]


def test_register_and_get_roundtrip():
    @register
    class Dummy(Scorer):
        name = "Dummy"

        def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
            return ScoreResult(scorer=self.name, value=1.0, passed=True)

    assert get("Dummy") is Dummy
    assert REGISTRY["Dummy"] is Dummy
    trace = Trace(id="t", name="n", start=0.0)
    assert Dummy().score(trace=trace).value == 1.0
