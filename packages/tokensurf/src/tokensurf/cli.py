"""TokenSurf command-line interface (`tokensurf eval ...`)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import typer

from tokensurf.eval.reporter import render_console, write_jsonl
from tokensurf.eval.runner import evaluate
from tokensurf.scaffold import write_project
from tokensurf.sdk.config import ConfigError, fetch_config
from tokensurf.sdk.push import PushError, push_report

app = typer.Typer(help="TokenSurf agent-quality CLI.")
eval_app = typer.Typer(help="Run and report agent evaluations.")
app.add_typer(eval_app, name="eval")

try:
    # Optional dependency: only importable when tokensurf-server is installed too.
    from tokensurf_server.admin_cli import (  # pyright: ignore[reportMissingImports]
        app as _server_app,
    )
except ModuleNotFoundError:
    _server_app = None

if _server_app is not None:
    app.add_typer(_server_app, name="server", help="Admin commands for a self-hosted server.")

_PROVIDER_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("tokensurf_eval_module", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@eval_app.command("run")
def run(
    file: str = typer.Argument(..., help="Python file exposing task, data, scorers."),
    output: str = typer.Option("results.jsonl", "--output", "-o", help="JSONL results path."),
    server: str | None = typer.Option(
        None,
        "--server",
        help="TokenSurf Server base URL (env: TOKENSURF_SERVER_URL).",
        envvar="TOKENSURF_SERVER_URL",
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="Project ingest API key (env: TOKENSURF_API_KEY).",
        envvar="TOKENSURF_API_KEY",
    ),
    label: str | None = typer.Option(
        None,
        "--label",
        help="Human-readable run label (e.g. branch name or git sha).",
    ),
    no_config_pull: bool = typer.Option(
        False,
        "--no-config-pull",
        help="Do not pull judge keys from the server before running.",
    ),
) -> None:
    """Run the eval defined in FILE, print the table, and write results.jsonl.

    When both --server and --key are supplied (or set via env vars), judge keys
    are pulled from the server and set as provider env vars before the eval runs
    (local env takes precedence; use --no-config-pull to skip). The resulting
    report is then pushed to the TokenSurf Server.

    NOTE: standalone ``tokensurf push RESULTS_JSONL`` is deferred. reporter.write_jsonl
    serialises individual EvalCaseResult rows, not a full EvalReport; no clean loader
    exists yet to reconstruct EvalReport from results.jsonl without fragile guesswork.
    """
    file_path = Path(file)
    if not file_path.exists():
        typer.echo(f"Error: file not found: {file_path}")
        raise typer.Exit(code=1)
    module = _load_module(file_path)
    missing = [a for a in ("task", "data", "scorers") if not hasattr(module, a)]
    if missing:
        typer.echo(f"Error: {file} must define module-level: {', '.join(missing)}")
        raise typer.Exit(code=1)

    if server and key and not no_config_pull:
        try:
            config = fetch_config(server_url=server, api_key=key)
            for provider, val in config.get("judge_keys", {}).items():
                env_var = _PROVIDER_ENV.get(provider)
                if env_var and not os.environ.get(env_var):
                    os.environ[env_var] = val
        except ConfigError as exc:
            typer.echo(f"Config pull failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    report = evaluate(task=module.task, data=module.data, scorers=module.scorers)
    typer.echo(render_console(report))
    write_jsonl(report, output)
    typer.echo(f"Wrote {output}")

    if server and key:
        try:
            ref = push_report(report, server_url=server, api_key=key, label=label)
            typer.echo(
                f"Pushed run {ref.run_id} to project '{ref.project}' "
                f"(pass_rate={ref.pass_rate:.3f}, n_cases={ref.n_cases})"
            )
        except PushError as exc:
            typer.echo(f"Push failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc


@eval_app.command("report")
def report(
    path: str = typer.Argument(..., help="Path to a results.jsonl file."),
) -> None:
    """Pretty-print a saved results.jsonl."""
    file_path = Path(path)
    if not file_path.exists():
        typer.echo(f"Error: file not found: {file_path}")
        raise typer.Exit(code=1)
    rows = [
        json.loads(line)
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    typer.echo(f"Cases: {len(rows)}")
    for row in rows:
        case_id = row.get("case", {}).get("id", "?")
        for score in row.get("scores", []):
            scorer = score.get("scorer", "?")
            value = score.get("value")
            error = score.get("error")
            passed = score.get("passed")
            status = "ERROR" if error else ("PASS" if passed else "FAIL")
            value_str = f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"
            typer.echo(f"  {case_id:<10} {scorer:<16} {status:<6} {value_str}")


@app.command("init")
def init(
    directory: str = typer.Argument("tokensurf-tests", help="Directory to scaffold into."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Scaffold a starter project: example evals + a pytest CI gate."""
    target = Path(directory)
    try:
        written = write_project(target, force=force)
    except FileExistsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Created {len(written)} files in {target}/:")
    for path in written:
        typer.echo(f"  {path}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(f"  cd {directory}")
    typer.echo("  tokensurf eval run evals/example_deterministic.py")
    typer.echo("  pytest evals/")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
