"""TokenSurf-Open: AI agent quality framework (Slice 1)."""

from __future__ import annotations

__version__ = "0.1.0"

# Core models
from tokensurf.core.models import Case, EvalReport, ScoreResult, Span, Trace

# Eval primitives
from tokensurf.eval.dataset import Dataset
from tokensurf.eval.runner import evaluate

# Pytest helper
from tokensurf.pytest_plugin import assert_eval

# Scorers — deterministic
from tokensurf.scorers.base import Scorer
from tokensurf.scorers.deterministic import (
    Contains,
    CostUnder,
    ExactMatch,
    JSONSchemaValid,
    LatencyUnder,
    Regex,
    ToolCalled,
)

# Scorers — LLM
from tokensurf.scorers.llm import LLMJudge

# Scorers — reference (EmbeddingSimilarity uses litellm lazily; importable even
# if the optional 'reference' extra is absent — only raises on actual score() call)
from tokensurf.scorers.reference import EmbeddingSimilarity

# Scorers — trajectory
from tokensurf.scorers.trajectory import (
    NoLoops,
    Recovery,
    StepBudget,
    TaskCompletion,
    ToolSequence,
)

# SDK tracking helpers
from tokensurf.sdk.track import current_trace, span, track

__all__ = [
    "__version__",
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
]
