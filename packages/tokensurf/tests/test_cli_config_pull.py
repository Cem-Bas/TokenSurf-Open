"""Tests for CLI config-pull integration (Slice 2d Group B3)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tokensurf.cli import app
from tokensurf.sdk.config import ConfigError
from tokensurf.sdk.push import RunRef

runner = CliRunner()

_FAKE_REF = RunRef(run_id="r1", project="proj", pass_rate=1.0, n_cases=1)

EXAMPLE_MODULE = """\
from tokensurf.core.models import ScoreResult
from tokensurf.eval.dataset import Dataset
from tokensurf.scorers.base import Scorer


class AlwaysPass(Scorer):
    name = "always_pass"

    def score(self, *, trace, case=None):
        return ScoreResult(scorer=self.name, value=1.0, passed=True)


def task(question):
    return f"answer: {question}"


data = Dataset.from_list([{"id": "c1", "input": "hi"}])
scorers = [AlwaysPass()]
"""


def _write_example(tmp_path):
    p = tmp_path / "example_eval.py"
    p.write_text(EXAMPLE_MODULE, encoding="utf-8")
    return p


def test_config_pull_sets_env_before_evaluate(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_config judge_keys openai sk-test-x -> OPENAI_API_KEY set before evaluate."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    captured: list[str | None] = []

    def _fake_evaluate(*, task, data, scorers):
        captured.append(os.environ.get("OPENAI_API_KEY"))
        from tokensurf.core.models import EvalReport

        return EvalReport(results=[])

    with patch("tokensurf.cli.fetch_config", return_value={"judge_keys": {"openai": "sk-test-x"}}):
        with patch("tokensurf.cli.evaluate", side_effect=_fake_evaluate):
            with patch("tokensurf.cli.push_report", return_value=_FAKE_REF):
                result = runner.invoke(
                    app,
                    [
                        "eval",
                        "run",
                        str(module_path),
                        "--output",
                        str(out_path),
                        "--server",
                        "http://ts.test",
                        "--key",
                        "tsk_abc",
                    ],
                )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0] == "sk-test-x"


def test_config_pull_does_not_overwrite_preset_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local env wins: OPENAI_API_KEY already set must not be overwritten by config pull."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-already-set")
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    captured: list[str | None] = []

    def _fake_evaluate(*, task, data, scorers):
        captured.append(os.environ.get("OPENAI_API_KEY"))
        from tokensurf.core.models import EvalReport

        return EvalReport(results=[])

    with patch(
        "tokensurf.cli.fetch_config", return_value={"judge_keys": {"openai": "sk-from-server"}}
    ):
        with patch("tokensurf.cli.evaluate", side_effect=_fake_evaluate):
            with patch("tokensurf.cli.push_report", return_value=_FAKE_REF):
                result = runner.invoke(
                    app,
                    [
                        "eval",
                        "run",
                        str(module_path),
                        "--output",
                        str(out_path),
                        "--server",
                        "http://ts.test",
                        "--key",
                        "tsk_abc",
                    ],
                )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0] == "sk-already-set"


def test_no_config_pull_flag_skips_fetch(tmp_path) -> None:
    """--no-config-pull must skip fetch_config entirely even when server+key are set."""
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    with patch("tokensurf.cli.fetch_config") as mock_fetch:
        with patch("tokensurf.cli.push_report", return_value=_FAKE_REF):
            result = runner.invoke(
                app,
                [
                    "eval",
                    "run",
                    str(module_path),
                    "--output",
                    str(out_path),
                    "--server",
                    "http://ts.test",
                    "--key",
                    "tsk_abc",
                    "--no-config-pull",
                ],
            )

    assert result.exit_code == 0, result.output
    mock_fetch.assert_not_called()


def test_config_pull_error_exits_nonzero(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ConfigError from fetch_config must cause CLI to exit non-zero before evaluate runs."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    with patch(
        "tokensurf.cli.fetch_config",
        side_effect=ConfigError("config pull failed: HTTP 401 — Invalid API key"),
    ):
        with patch("tokensurf.cli.evaluate") as mock_evaluate:
            result = runner.invoke(
                app,
                [
                    "eval",
                    "run",
                    str(module_path),
                    "--output",
                    str(out_path),
                    "--server",
                    "http://ts.test",
                    "--key",
                    "tsk_abc",
                ],
            )

    assert result.exit_code != 0
    mock_evaluate.assert_not_called()
