"""End-to-end smoke test for the reference/embedding-scorer example."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "reference_scorer.py"


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reference_scorer", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_example_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_example()
    report = mod.main()

    out = capsys.readouterr().out
    assert "EmbeddingSimilarity" in out

    assert len(report.results) == 3
    assert report.error_count() == 0

    # c1 and c2's outputs produce bag-of-words vectors identical to their
    # expected text's vectors (the words that do overlap - "capital"/"france"
    # for c1, "capital"/"japan" for c2 - are the only nonzero vocab dims on
    # both sides once trailing punctuation is stripped by the fake
    # tokenizer's whitespace split), so cosine similarity is ~1.0 and both
    # pass. c3's output ("sky"/"blue") shares no vocab word with its
    # (deliberately mismatched) expected text ("capital"/"france"), so cosine
    # similarity is 0.0 and it fails against threshold=0.5.
    assert report.pass_rate() == pytest.approx(2 / 3)


def test_reference_example_runs_as_a_script() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "EmbeddingSimilarity" in proc.stdout
