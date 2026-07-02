# What is TokenSurf

TokenSurf is an open-source, Apache-2.0, self-hosted framework for scoring the quality of AI agent
runs — "pytest for agents". It pairs a scoring engine, a lightweight capture SDK, and an offline
evaluation harness you can run in CI, plus an optional collector server that adds a dashboard,
quality gates, notifications, and centralized judge-key management. Everything runs inside your own
trust boundary: no external data path, no managed dependency.

## A dozen lines to a first eval

```python
import tokensurf as ts

@ts.track
def my_agent(question: str) -> str:
    with ts.span("kb_lookup", type="tool", input=question):
        ...                       # call your tools and models however you like
    return "..."

report = ts.evaluate(
    task=my_agent,
    data=ts.Dataset.from_jsonl("cases.jsonl"),
    scorers=[ts.ExactMatch(), ts.ToolCalled(name="kb_lookup")],
)
print(f"pass rate: {report.pass_rate():.0%}")
```

- `@ts.track` captures each call as a trace; `ts.span(...)` records the steps inside it.
- `ts.evaluate(task=..., data=..., scorers=...)` runs every case through your agent and grades the
  captured traces with the scorers you chose. It returns an `EvalReport`.
- In CI, `ts.assert_eval(report, min_pass_rate=0.9)` fails the build when quality regresses, or run
  the same eval from the command line with `tokensurf eval run eval.py` (the file exposes
  module-level `task`, `data`, and `scorers`).

## What is in the box

- **Scoring engine** — 14 scorers in four families (see the table below). Every score is
  normalized to 0.0–1.0, and scorer failures never abort a run: they surface as errored results.
- **Capture SDK** — the `@track` decorator, the `span()` context manager, and local sinks (SQLite,
  JSONL). Framework-agnostic: it wraps your functions and never proxies your model traffic, and
  sink writes are best-effort, so capture can never break your agent.
- **Offline eval harness** — `Dataset` (from lists, JSONL, or CSV), `evaluate()`, `EvalReport`
  aggregates, a console/JSONL reporter, the `assert_eval` pytest helper, and the `tokensurf eval`
  CLI. Runs entirely on your machine or CI runner; no server required.
- **Collector server (optional)** — `tokensurf-server`, a self-hosted FastAPI + Postgres service.
  Push eval runs to it with a per-project API key; it stores them, renders a dashboard with run
  history and trends, evaluates quality gates on every ingested run, fires Slack / webhook / email
  notifications, and serves judge keys (stored encrypted at rest, decrypted only at pull time)
  back to the CLI via config pull.

## Who it is for

- Teams shipping AI agents who want quality measured like tests: datasets, scorers, pass rates,
  and a CI gate — not vibes.
- Self-hosters and regulated environments: traces, datasets, and judge keys stay on infrastructure
  you control.
- Anyone grading more than the final answer: trajectory scorers check tool ordering, loops, step
  budgets, and recovery across the whole multi-step run.

## The four scorer families

| Family | Scorers | Model call |
|--------|---------|------------|
| Deterministic | `ExactMatch`, `Contains`, `Regex`, `JSONSchemaValid`, `LatencyUnder`, `CostUnder`, `ToolCalled` | None — code-based assertions, reproducible and free |
| LLM judge | `LLMJudge` | Yes — grades against your criteria on a 1–10 rubric, provider-agnostic via litellm |
| Reference-based | `EmbeddingSimilarity` | Embeddings — cosine similarity between output and `case.expected` |
| Agent trajectory | `ToolSequence`, `NoLoops`, `StepBudget`, `TaskCompletion`, `Recovery` | Only `TaskCompletion` (delegates to an `LLMJudge`) |

Every scorer returns a `ScoreResult` with a value normalized to 0.0–1.0 (or `None` when the
scorer errors). The full reference, including constructor arguments for each scorer, is in
[Scorers](scorers.md).

## Architecture

```text
 your agent code           offline eval (local or CI)      self-hosted, optional
+-----------------+ traces +-----------------------+  push  +------------------------+
| capture SDK     |------->| eval harness          |------->| TokenSurf Server       |
| @track / span() |        | evaluate() + scorers  | HTTPS  | dashboard: runs/trends |
+-----------------+        | tokensurf eval run    | + key  | quality gates          |
                           +-----------------------+        | Slack/webhook/email    |
                                     ^                      | encrypted judge keys   |
                                     |                      +------------+-----------+
                                     +--- config pull (judge keys) -----+
```

The SDK and eval harness are fully usable on their own — results print to the console and write to
JSONL locally. Adding `--server` and `--key` to `tokensurf eval run` pushes the report to your
TokenSurf Server, where it appears on the dashboard, quality gates evaluate automatically, and any
breach notifies your Slack, webhook, or email channels. Before running, the CLI can also pull
judge-provider keys stored (encrypted) on the server, so CI jobs need only one secret: the project
API key. Local environment variables always win over pulled keys.

## Status

TokenSurf is pre-1.0: both packages are version 0.1.0 and public APIs may change before the first
tagged release. The packages are not yet published to PyPI, so installation is from source only:

```bash
git clone <repository-url>
cd TokenSurf
uv sync
```

This sets up the uv workspace containing the `tokensurf` SDK and the `tokensurf-server` collector.
Python 3.11 or newer is required. Licensed under Apache-2.0.

## Where next

- [Quickstart](quickstart.md) — install from source and run your first eval end to end.
- [Capture SDK](sdk.md) — `@track`, `span()`, traces, spans, and local sinks.
- [Scorers](scorers.md) — the full reference for all 14 scorers and their arguments.
- [CLI](cli.md) — `tokensurf eval run` and `tokensurf eval report`, flags and env vars.
- [Self-hosting](self-hosting.md) — run the collector server: Docker Compose, migrations,
  and the admin CLI.
- [Quality gates and notifications](quality-gates.md) — gate runs on pass rate, mean score, or
  per-scorer pass rate; alert via Slack, webhook, or email.
- [Config pull](config-pull.md) — store judge keys on the server and pull them at eval time.
- [Security](security.md) — auth model, secret encryption at rest, and deployment hardening.
