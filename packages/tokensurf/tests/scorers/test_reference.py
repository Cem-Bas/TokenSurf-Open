from tokensurf.core.models import Case
from tokensurf.scorers.reference import EmbeddingSimilarity


def test_embedding_similarity_high(fake_embedder, make_trace):
    trace = make_trace(output="the cat sat")
    case = Case(id="c", input="q", expected="the cat sat")
    client = fake_embedder([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    result = EmbeddingSimilarity(client=client, threshold=0.8).score(trace=trace, case=case)
    assert result.value == 1.0
    assert result.passed is True


def test_embedding_similarity_low(fake_embedder, make_trace):
    trace = make_trace(output="apples")
    case = Case(id="c", input="q", expected="oranges")
    client = fake_embedder([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    result = EmbeddingSimilarity(client=client, threshold=0.8).score(trace=trace, case=case)
    assert result.value == 0.0
    assert result.passed is False


def test_embedding_similarity_no_reference(fake_embedder, make_trace):
    result = EmbeddingSimilarity(client=fake_embedder([])).score(
        trace=make_trace(output="x"), case=None
    )
    assert result.error is not None
    assert result.value is None
