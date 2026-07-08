<div align="center">

# 🏄 TokenSurf

**pytest for AI agents — score, evaluate, and gate agent quality, entirely on your own infrastructure.**

[![CI](https://github.com/Cem-Bas/TokenSurf-Open/actions/workflows/ci.yml/badge.svg)](https://github.com/Cem-Bas/TokenSurf-Open/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

[Quickstart](docs/quickstart.md) · [Scorers](docs/scorers.md) · [SDK](docs/sdk.md) · [Self-hosting](docs/self-hosting.md) · [Security model](docs/security.md)

*Pre-1.0 — not yet on PyPI; install from source.*

</div>

---

Agent systems regress quietly. A prompt tweak, a model upgrade, or a tool change ships — and answer
quality drops with **no failing test to catch it**. TokenSurf gives your agents the test harness
the rest of your code already has:

- a **capture SDK** records each agent run as a trace,
- **14 scorers** grade traces from 0.0 to 1.0,
- an **offline eval harness** turns datasets of cases into pass/fail verdicts you enforce in CI,
- an optional **self-hosted server** adds a dashboard, quality gates, and alerts.

No managed service, no telemetry, Apache-2.0. Your traces, datasets, and keys stay on
infrastructure you control — the only outbound calls are the ones you opt into by using a hosted
LLM-judge or embedding provider.

## A dozen lines to your first eval

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

Then gate CI with one line — the build fails when quality regresses:

```python
ts.assert_eval(report, min_pass_rate=0.9)
```

Or run it from the command line — save the task, data, and scorers as an eval file
([format below](#quickstart)) and get a console table plus JSONL results:

```text
$ tokensurf eval run eval.py
Cases: 3
scorer                    pass_rate     mean   errors
-----------------------------------------------------
ExactMatch                    0.667    0.667        0
ToolCalled                    1.000    1.000        0
Total errors: 0
Wrote results.jsonl
```

`evaluate()` traces each task call by itself, so eval files don't need the decorator —
`@ts.track` is for capturing runs in your live app.

## Why TokenSurf

Most eval tooling grades single prompt–response pairs on someone else's cloud. TokenSurf grades
whole agent runs on yours.

- **Grade the whole run, not just the final answer.** Trajectory scorers check tool ordering,
  loops, step budgets, task completion, and error recovery across the entire multi-step run.
- **Deterministic first, LLM-judge when you need it.** Seven scorers are pure code — no model
  call, no flakiness; `LLMJudge` and `EmbeddingSimilarity` cover the fuzzy cases.
- **Capture that can never break your agent.** The `@track` decorator wraps your functions — it
  never proxies your model traffic, and trace writes are best-effort: a failed write can never
  raise into your code.
- **Runs fully offline.** No server, no network — `evaluate()` and `tokensurf eval run` work
  anywhere pytest does.
- **Your trust boundary, your data.** The optional collector server is self-hosted
  FastAPI + Postgres — with a dashboard, quality gates, Slack/webhook/email alerts, encrypted
  judge keys, and an audit log.

## Scorers at a glance

| Family | Scorers | Model call |
|--------|---------|------------|
| Deterministic | `ExactMatch`, `Contains`, `Regex`, `JSONSchemaValid`, `LatencyUnder`, `CostUnder`, `ToolCalled` | None — code-based, reproducible, free |
| LLM judge | `LLMJudge` | Yes — grades against your criteria, provider-agnostic via litellm |
| Reference-based | `EmbeddingSimilarity` | Embeddings — cosine similarity vs. `case.expected` |
| Agent trajectory | `ToolSequence`, `NoLoops`, `StepBudget`, `TaskCompletion`, `Recovery` | Only `TaskCompletion` (delegates to an `LLMJudge`) |

Every score is normalized to 0.0–1.0, and scorer failures never abort a run — they surface as
errored results. You can also [write your own scorer](docs/scorers.md).

## How it fits together

```text
 your agent code           offline eval (local or CI)      self-hosted, optional
+-----------------+ traces +-----------------------+  push  +------------------------+
| capture SDK     |------->| eval harness          |------->| TokenSurf Server       |
| @track / span() |        | evaluate() + scorers  | HTTPS  | dashboard: runs/trends |
+-----------------+        | tokensurf eval run    | + key  | quality gates          |
                           +-----------------------+        | Slack/webhook/email    |
                                     ^                      | encrypted judge keys   |
                                     |                      +------------+-----------+
                                     +--- config pull (judge keys) ------+
```

The SDK and eval harness are fully usable on their own. Add `--server` and `--key` to push runs to
your TokenSurf Server — and CI jobs need only that one secret, because the CLI pulls
judge-provider keys (stored encrypted) from the server at eval time.

## Quickstart

Install from source — TokenSurf is pre-1.0, and public APIs may still change before the first
tagged release:

```bash
git clone https://github.com/Cem-Bas/TokenSurf-Open.git
cd TokenSurf-Open
uv sync
```

The fastest way in — scaffold a runnable starter project (example evals + a pytest CI gate):

```bash
uv run tokensurf init my-tests
uv run tokensurf eval run my-tests/evals/example_deterministic.py
```

Or write an eval by hand — a plain Python file exposing module-level `task`, `data`, and
`scorers`. Save the following as `eval.py`:

```python
import tokensurf as ts

def task(question: str) -> str:
    with ts.span("lookup", type="tool", input=question) as sp:
        sp.output = "Paris" if "France" in question else "I don't know"
        return sp.output

data = ts.Dataset.from_list([
    {"id": "c1", "input": "capital of France", "expected": "Paris"},
])

scorers: list[ts.Scorer] = [ts.ExactMatch(), ts.ToolSequence(expected=["lookup"])]
```

```bash
uv run tokensurf eval run eval.py    # console table + results.jsonl
```

Full walkthrough — including the pytest gate and pushing runs to a server:
[Quickstart](docs/quickstart.md).

## Self-hosting the server

The dev stack is one command; migrations run at container start:

```bash
docker compose up -d                                 # Postgres 16 + server on :8000
docker compose exec app cat tokensurf_setup_token    # first-run setup token
```

Open `http://localhost:8000` — while no admin account exists, every page redirects to the
**`/setup` wizard**. Paste the token (proof you're the operator, not whoever reaches the port
first) and create the first admin. Then mint a project and an ingest key:

```bash
docker compose exec app uv run tokensurf-server create-project "My Agent"       # prints slug=my-agent
docker compose exec app uv run tokensurf-server create-key my-agent --label ci  # raw key, printed once
```

Re-run your eval with `--server http://localhost:8000 --key tsk_...` and the run appears on the
dashboard. Change every `changeme` credential in `docker-compose.yml` before non-local use.
Production setup, environment variables, and the full admin CLI:
[Self-hosting](docs/self-hosting.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [What is TokenSurf](docs/index.md) | Overview, architecture, and how the pieces fit together |
| [Quickstart](docs/quickstart.md) | Fresh clone to a scored eval, then pushing runs to a server |
| [SDK reference](docs/sdk.md) | `@track`, `span()`, sinks, `Dataset`, `evaluate()`, `assert_eval` |
| [Scorers](docs/scorers.md) | The 14 built-in scorers in four families, and writing your own |
| [CLI reference](docs/cli.md) | `tokensurf init` / `eval run` / `eval report`; `tokensurf-server` admin |
| [Self-hosting](docs/self-hosting.md) | Compose or manual install, setup wizard, production setup |
| [Gates & alerts](docs/quality-gates.md) | Per-project quality gates; Slack/webhook/email alerts |
| [Judge keys & config pull](docs/config-pull.md) | Encrypted provider keys, pulled by CI at eval |
| [Security model](docs/security.md) | Trust boundary, auth, CSRF, rate limiting, audit log |

## Repository layout

```text
packages/tokensurf/         # library: capture SDK, scorers, eval harness, `tokensurf` CLI
packages/tokensurf-server/  # self-hosted collector: FastAPI + Postgres, dashboard, admin CLI
docs/                       # documentation (table above)
docker-compose.yml          # dev stack: Postgres 16 + server
```

## Development

Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync                                        # install both packages + dev tools

uv run --directory packages/tokensurf pytest   # library tests (no external services)

# server tests need a running Postgres, e.g. `docker compose up -d db`
DATABASE_URL=postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf \
  uv run --directory packages/tokensurf-server pytest

# lint + type-check (run in each package directory)
uv run --directory packages/tokensurf ruff check .
uv run --directory packages/tokensurf pyright
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide — including the opt-in
destructive migration tests.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
