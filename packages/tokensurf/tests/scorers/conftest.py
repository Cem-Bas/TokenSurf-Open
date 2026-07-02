import pytest

from tokensurf.core.models import Case, Span, SpanType, Trace
from tokensurf.scorers.llm import LLMResponse


class FakeLLMClient:
    """No-network LLMClient double for tests (needs no API key)."""

    def __init__(self, responses=None, *, raises: int = 0):
        self._responses = list(responses or [])
        self._raises = raises
        self.calls: list[dict] = []

    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse:
        self.calls.append({"model": model, "messages": messages})
        if self._raises > 0:
            self._raises -= 1
            raise RuntimeError("fake transport error")
        text = self._responses.pop(0) if self._responses else "8"
        return LLMResponse(text=text, model=model, cost=0.0001, latency=0.01)


@pytest.fixture
def fake_llm():
    def _make(responses=None, *, raises: int = 0) -> FakeLLMClient:
        return FakeLLMClient(responses=responses, raises=raises)

    return _make


@pytest.fixture
def sample_trace() -> Trace:
    return Trace(
        id="t1",
        name="agent",
        input="What is 2+2?",
        output="The answer is 4.",
        start=0.0,
        end=1.5,
        spans=[
            Span(
                id="s1", name="search", type="tool", start=0.0, end=0.5, attributes={"cost": 0.002}
            ),
            Span(
                id="s2",
                name="calculator",
                type="tool",
                start=0.5,
                end=1.0,
                attributes={"cost": 0.001},
            ),
        ],
    )


@pytest.fixture
def sample_case() -> Case:
    return Case(id="c1", input="What is 2+2?", expected="The answer is 4.")


@pytest.fixture
def make_span():
    def _make(
        name,
        *,
        type: SpanType = "tool",
        start=0.0,
        end=1.0,
        error=None,
        output=None,
        attributes=None,
    ):
        return Span(
            id=name,
            name=name,
            type=type,
            start=start,
            end=end,
            error=error,
            output=output,
            attributes=attributes or {},
        )

    return _make


@pytest.fixture
def make_trace():
    def _make(spans=None, *, input="q", output="a", start=0.0, end=1.0):
        return Trace(
            id="t",
            name="agent",
            input=input,
            output=output,
            start=start,
            end=end,
            spans=list(spans or []),
        )

    return _make


class FakeEmbeddingClient:
    """No-network embedding double; returns preset vectors in call order.

    Also implements ``complete`` (unused) so it is structurally an LLMClient.
    """

    def __init__(self, vectors):
        self._vectors = vectors

    def complete(self, *, model, messages):
        raise NotImplementedError

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        return [self._vectors[i] for i in range(len(texts))]


@pytest.fixture
def fake_embedder():
    def _make(vectors) -> FakeEmbeddingClient:
        return FakeEmbeddingClient(vectors)

    return _make
