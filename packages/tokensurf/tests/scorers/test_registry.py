import tokensurf.scorers as scorers
from tokensurf.scorers.base import REGISTRY, get

EXPECTED = {
    "ExactMatch",
    "Contains",
    "Regex",
    "JSONSchemaValid",
    "LatencyUnder",
    "CostUnder",
    "ToolCalled",
    "LLMJudge",
    "EmbeddingSimilarity",
    "ToolSequence",
    "NoLoops",
    "StepBudget",
    "TaskCompletion",
    "Recovery",
}


def test_all_scorers_exported_and_registered():
    for name in EXPECTED:
        assert hasattr(scorers, name), f"{name} missing from tokensurf.scorers"
        assert name in REGISTRY, f"{name} not registered"
        assert get(name) is getattr(scorers, name)


def test_helper_exports_present():
    for name in (
        "Scorer",
        "register",
        "get",
        "REGISTRY",
        "LLMClient",
        "LLMResponse",
        "LiteLLMClient",
    ):
        assert hasattr(scorers, name)
