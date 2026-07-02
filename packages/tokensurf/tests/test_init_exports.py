"""TDD: verify that `import tokensurf as ts` exposes the full public API."""

import tokensurf as ts

EXPECTED_NAMES = [
    # core models
    "Trace",
    "Span",
    "Case",
    "ScoreResult",
    "EvalReport",
    # scorers
    "Scorer",
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
    # sdk
    "track",
    "span",
    "current_trace",
    # eval
    "Dataset",
    "evaluate",
    # pytest helper
    "assert_eval",
    # version
    "__version__",
]


def test_all_public_names_present():
    for name in EXPECTED_NAMES:
        assert hasattr(ts, name), f"tokensurf.{name} is missing from package root"


def test_all_listed_in_dunder_all():
    for name in EXPECTED_NAMES:
        assert name in ts.__all__, f"{name!r} is missing from tokensurf.__all__"


def test_version_value():
    assert ts.__version__ == "0.1.0"
