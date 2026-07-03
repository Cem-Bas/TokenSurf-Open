# TokenSurf

Open-source AI-agent-quality framework: score, evaluate, and gate your agents — "pytest for
agents" — entirely inside your own trust boundary.

> **Status:** pre-1.0 and launching soon. Public APIs are still stabilizing, and the packages are
> not yet on PyPI — install from source as shown below.

Agent systems regress quietly: a prompt tweak, a model upgrade, or a tool change ships, and answer
quality drops with no failing test to catch it. TokenSurf gives agents the test harness ordinary
code already has — a capture SDK records each run as a trace, scorers grade traces from 0 to 1,
and an offline eval harness turns datasets of cases into pass/fail verdicts you can enforce in CI.
Nothing leaves your infrastructure: the optional collector server is self-hosted.

- **14 scorers in four families** — deterministic checks (exact/contains/regex/JSON-schema/
  latency/cost/tool-called), an LLM judge, reference-based embedding similarity, and trajectory
  scorers that grade the whole multi-step run (tool order, loops, step budget, completion,
  recovery).
- **`@track` capture SDK** — one decorator records a run as a `Trace` with typed spans; sink
  writes are best-effort and never break your agent.
- **Eval harness built for CI** — `Dataset` + `evaluate()` + `assert_eval`, plus a
  `tokensurf eval run` CLI that prints a console table and writes JSONL results.
- **Self-hosted server (optional)** — FastAPI + Postgres collector with a dashboard, per-project
  quality gates, Slack/webhook/email alerts, encrypted judge keys with CI config pull, and an
  audit log.

## Quickstart

From a clone of this repository, `uv sync` installs the workspace.

The fastest way in: `uv run tokensurf init my-tests` scaffolds a runnable starter project (example
evals + a pytest CI gate). Or write one by hand:

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

Add `--server https://tokensurf.example.com --key tsk_...` to push the run to your server. Full
walkthrough, including the pytest gate: [Quickstart](docs/quickstart.md).

## Self-hosting the server

The dev stack is one command; migrations run at container start:

```bash
docker compose up -d      # Postgres 16 + server on http://localhost:8000
docker compose exec app uv run tokensurf-server create-user you@example.com
docker compose exec app uv run tokensurf-server create-project "My Agent"
docker compose exec app uv run tokensurf-server create-key my-agent --label ci  # raw key, once
```

Change every `changeme` credential in `docker-compose.yml` before non-local use. Production setup,
environment variables, and the full admin CLI: [Self-hosting](docs/self-hosting.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [What is TokenSurf](docs/index.md) | Overview, architecture, and how the pieces fit together |
| [Quickstart](docs/quickstart.md) | Fresh clone to a scored eval, then pushing runs to a server |
| [SDK reference](docs/sdk.md) | `@track`, `span()`, sinks, `Dataset`, `evaluate()`, `assert_eval` |
| [Scorers](docs/scorers.md) | The 14 built-in scorers in four families, and writing your own |
| [CLI reference](docs/cli.md) | `tokensurf eval run` / `eval report`; `tokensurf-server` admin |
| [Self-hosting](docs/self-hosting.md) | Compose or manual install, bootstrap, production setup |
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

Python >= 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync                                        # install both packages + dev tools

uv run --directory packages/tokensurf pytest   # library tests (no external services)

# server tests need a running Postgres, e.g. `docker compose up -d db`
DATABASE_URL=postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf \
  uv run --directory packages/tokensurf-server pytest

# destructive migration tests (drop all tables in DATABASE_URL) are opt-in — use a throwaway DB:
TOKENSURF_DESTRUCTIVE_DB_TESTS=1 DATABASE_URL=... \
  uv run --directory packages/tokensurf-server pytest

# lint + type-check (run in each package directory)
uv run --directory packages/tokensurf ruff check .
uv run --directory packages/tokensurf pyright
```

## License

Apache-2.0. See [LICENSE](LICENSE).
