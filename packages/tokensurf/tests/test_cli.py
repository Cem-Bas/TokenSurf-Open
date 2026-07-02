import json
from unittest.mock import patch

from typer.testing import CliRunner

from tokensurf.cli import app
from tokensurf.sdk.push import RunRef

runner = CliRunner()

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


data = Dataset.from_list([{"id": "c1", "input": "hi"}, {"id": "c2", "input": "bye"}])
scorers = [AlwaysPass()]
"""


def _write_example(tmp_path):
    module_path = tmp_path / "example_eval.py"
    module_path.write_text(EXAMPLE_MODULE, encoding="utf-8")
    return module_path


def test_eval_run_prints_table_and_writes_results(tmp_path):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"
    result = runner.invoke(app, ["eval", "run", str(module_path), "--output", str(out_path)])
    assert result.exit_code == 0, result.output
    assert "always_pass" in result.output
    assert "pass_rate" in result.output
    assert out_path.exists()
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["case"]["id"] == "c1"
    assert first["scores"][0]["scorer"] == "always_pass"


def test_eval_run_errors_when_module_missing_symbols(tmp_path):
    bad = tmp_path / "bad_eval.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(app, ["eval", "run", str(bad)])
    assert result.exit_code != 0
    assert "task" in result.output


def test_eval_report_pretty_prints_results(tmp_path):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"
    run_result = runner.invoke(app, ["eval", "run", str(module_path), "--output", str(out_path)])
    assert run_result.exit_code == 0, run_result.output

    report_result = runner.invoke(app, ["eval", "report", str(out_path)])
    assert report_result.exit_code == 0, report_result.output
    assert "Cases: 2" in report_result.output
    assert "always_pass" in report_result.output
    assert "PASS" in report_result.output


# ── Task D2: push-wiring tests ────────────────────────────────────────────────
_FAKE_REF = RunRef(run_id="r1", project="proj", pass_rate=1.0, n_cases=2)


def test_eval_run_calls_push_when_server_and_key_given(tmp_path):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    with patch("tokensurf.cli.push_report", return_value=_FAKE_REF) as mock_push:
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
                "--label",
                "ci-run",
                "--no-config-pull",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_push.assert_called_once()
    call = mock_push.call_args
    from tokensurf.core.models import EvalReport

    assert isinstance(call.args[0], EvalReport)
    assert call.kwargs["server_url"] == "http://ts.test"
    assert call.kwargs["api_key"] == "tsk_abc"
    assert call.kwargs["label"] == "ci-run"
    assert "r1" in result.output


def test_eval_run_does_not_call_push_when_server_absent(tmp_path):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    with patch("tokensurf.cli.push_report") as mock_push:
        result = runner.invoke(
            app,
            ["eval", "run", str(module_path), "--output", str(out_path)],
        )

    assert result.exit_code == 0, result.output
    mock_push.assert_not_called()


def test_eval_run_does_not_call_push_when_key_absent(tmp_path):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    with patch("tokensurf.cli.push_report") as mock_push:
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
            ],
        )

    assert result.exit_code == 0, result.output
    mock_push.assert_not_called()


def test_eval_run_reads_server_and_key_from_env(tmp_path, monkeypatch):
    module_path = _write_example(tmp_path)
    out_path = tmp_path / "results.jsonl"

    monkeypatch.setenv("TOKENSURF_SERVER_URL", "http://env.test")
    monkeypatch.setenv("TOKENSURF_API_KEY", "tsk_env")

    with patch("tokensurf.cli.push_report", return_value=_FAKE_REF) as mock_push:
        result = runner.invoke(
            app,
            ["eval", "run", str(module_path), "--output", str(out_path), "--no-config-pull"],
        )

    assert result.exit_code == 0, result.output
    mock_push.assert_called_once()
    call = mock_push.call_args
    assert call.kwargs["server_url"] == "http://env.test"
    assert call.kwargs["api_key"] == "tsk_env"
