# Quickstart

This page takes you from a fresh clone to a scored evaluation of an agent, and optionally to a run
pushed to a self-hosted TokenSurf Server. Everything runs offline — the example needs no provider
API key.

## 1. Install from source

TokenSurf is not yet published to PyPI. Install it from source with [uv](https://docs.astral.sh/uv/)
(Python 3.11+ required):

```bash
git clone https://github.com/Cem-Bas/TokenSurf-Open.git
cd TokenSurf-Open
uv sync
```

Check that the CLI is available:

```bash
uv run tokensurf --help
```

## 2. Scaffold a starter project (fastest path in)

```bash
uv run tokensurf init my-agent-tests
uv run tokensurf eval run my-agent-tests/evals/example_deterministic.py
```

This generates `evals/example_deterministic.py`, `evals/example_llm_judge.py`, a
`evals/test_agent_quality.py` pytest gate, and a README — a runnable starting point you edit
in place. The rest of this page shows what those generated files do and how to write your own
from scratch.

## 3. Write an eval file

An eval file is a plain Python file that defines three module-level names: `task` (the callable
under test), `data` (a `Dataset` of cases), and `scorers` (a list of `Scorer` instances). Save the
following as `eval.py`:

```python
"""eval.py — a complete TokenSurf eval: module-level task, data, scorers."""

import tokensurf as ts

_ANSWERS = {
    "capital of France": "Paris",
    "capital of Japan": "Tokyo",
    "2 + 2": "5",  # deliberately wrong — demonstrates a failing case
}


def task(question: str) -> str:
    """Your agent. The eval runner tracks it, so spans land on the trajectory."""
    with ts.span("lookup", type="tool", input=question) as sp:
        answer = _ANSWERS.get(question, "I don't know")
        sp.output = answer
    return answer


data = ts.Dataset.from_list(
    [
        {"id": "c1", "input": "capital of France", "expected": "Paris"},
        {"id": "c2", "input": "capital of Japan", "expected": "Tokyo"},
        {"id": "c3", "input": "2 + 2", "expected": "4"},
    ]
)

scorers: list[ts.Scorer] = [
    ts.ExactMatch(),  # output == expected, as strings
    ts.ToolSequence(expected=["lookup"]),  # trajectory: the lookup tool ran, in order
]
```

What each piece does:

- `task` is called once per case with `case.input` as its argument. You do not need `@ts.track`
  here — the eval runner wraps the task itself, so the `ts.span(...)` block inside it is captured
  as a tool span on the run's trajectory.
- `Dataset.from_list` builds cases from dicts with keys `input`, `expected`, and optional `id` and
  `metadata` — when `id` is omitted, a uuid4 hex id is generated for the case.
  `Dataset.from_jsonl(path)` and `Dataset.from_csv(path)` load the same shape from files.
- `ExactMatch()` is a deterministic scorer: it compares the task output against `case.expected`.
  `ToolSequence(expected=["lookup"])` is a trajectory scorer: it checks that the run's tool spans
  contain `"lookup"` in order. See [Scorers](scorers.md) for the full catalog.

## 4. Run the eval

```bash
uv run tokensurf eval run eval.py
```

You get a per-scorer summary table on stdout and a `results.jsonl` file:

```text
Cases: 3
scorer                    pass_rate     mean   errors
-----------------------------------------------------
ExactMatch                    0.667    0.667        0
ToolSequence                  1.000    1.000        0
Total errors: 0
Wrote results.jsonl
```

`ExactMatch` fails on case `c3` (the agent answers "5" instead of "4"), so its pass rate is 0.667.
`errors` counts scorer errors (a scorer that raised), not failed cases.

`results.jsonl` holds one JSON object per case, containing the `case`, the full captured `trace`
(including spans, timing, and any error) and the list of `scores`. The default `--output` path is
relative to your current working directory, so the file lands wherever you run the command from.
Pretty-print it any time with:

```bash
uv run tokensurf eval report results.jsonl
```

```text
Cases: 3
  c1         ExactMatch       PASS   1.000
  c1         ToolSequence     PASS   1.000
  c2         ExactMatch       PASS   1.000
  c2         ToolSequence     PASS   1.000
  c3         ExactMatch       FAIL   0.000
  c3         ToolSequence     PASS   1.000
```

Options for `tokensurf eval run`:

| Flag | Default | Description |
| --- | --- | --- |
| `FILE` (argument) | required | Python file exposing module-level `task`, `data`, `scorers` |
| `--output`, `-o` | `results.jsonl` | JSONL results path |
| `--server` | none (env: `TOKENSURF_SERVER_URL`) | TokenSurf Server base URL |
| `--key` | none (env: `TOKENSURF_API_KEY`) | Project ingest API key |
| `--label` | none | Human-readable run label (e.g. branch name or git sha) |
| `--no-config-pull` | off | Do not pull judge keys from the server before running |

## 5. Optional: push runs to a self-hosted server

TokenSurf Server is a self-hosted FastAPI + Postgres collector with a dashboard, quality gates,
and notifications. It runs inside your own trust boundary. This section shows the shortest local
path; see [Self-hosting](self-hosting.md) for the full setup (Docker, encryption keys, gates,
channels).

Start Postgres (the repo's compose file ships a dev database with placeholder credentials), then
migrate and serve:

```bash
docker compose up -d db

export DATABASE_URL="postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"
export TOKENSURF_SESSION_SECRET="$(openssl rand -hex 32)"

uv run --directory packages/tokensurf-server tokensurf-server migrate
uv run --directory packages/tokensurf-server uvicorn tokensurf_server.app:app --port 8000
```

The server refuses to start if `TOKENSURF_SESSION_SECRET` is unset or shorter than 32 characters —
generate a random one as shown.

In a second terminal (with the same `DATABASE_URL` exported), create a project and mint an ingest
API key. The raw key (prefix `tsk_`) is printed exactly once; the server stores only its SHA-256
hash plus an 11-character display prefix — never the full key:

```bash
export DATABASE_URL="postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf"

uv run --directory packages/tokensurf-server tokensurf-server create-project "My Agent"
uv run --directory packages/tokensurf-server tokensurf-server create-key my-agent --label ci
```

Re-run the eval with the server URL and the key that `create-key` printed:

```bash
uv run tokensurf eval run eval.py \
  --server http://localhost:8000 \
  --key tsk_your_key_here \
  --label quickstart
```

After the usual table you see the push confirmation:

```text
Pushed run <run_id> to project 'my-agent' (pass_rate=0.833, n_cases=3)
```

When `--server` and `--key` are both set, the CLI also pulls judge provider keys from the server
before the eval runs and exports them as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or
`GEMINI_API_KEY` — but only for variables not already set locally (your local environment wins).
Pass `--no-config-pull` to skip this. The quickstart eval needs no provider key either way.

To see the run in the dashboard, create a dashboard user (you will be prompted for a password) and
log in at `http://localhost:8000/login`:

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-user you@example.com
```

The run appears under your project with per-case scores and the captured trajectory.

## 6. Gate CI with pytest

`assert_eval` turns a report into a pass/fail test: it raises `AssertionError` (including the
console summary) when the pass rate is below your threshold. Save this next to `eval.py` as
`test_agent_quality.py`:

```python
"""test_agent_quality.py — gate agent quality in CI with assert_eval."""

import tokensurf as ts

from eval import data, scorers, task


def test_agent_quality() -> None:
    report = ts.evaluate(task=task, data=data, scorers=scorers)

    # Overall: at least half of all scores must pass.
    ts.assert_eval(report, min_pass_rate=0.5)

    # Per scorer: the agent must always call its tools in the right order.
    ts.assert_eval(report, min_pass_rate=1.0, scorer="ToolSequence")
```

```bash
uv run pytest test_agent_quality.py
```

Without `scorer`, `min_pass_rate` applies to the pooled pass rate across all scorers and cases;
with `scorer="ToolSequence"` it applies to that scorer alone. `evaluate()` never aborts on a task
or scorer exception — failures are recorded on the trace and as errored scores, so your test
verdict comes only from `assert_eval`.

## Next steps

- [Scorers](scorers.md) — the four scorer families (deterministic, LLM judge, reference-based,
  trajectory) and how to write your own.
- `packages/tokensurf/examples/quickstart_eval.py` — the repo's canonical variant of this eval,
  which adds an `LLMJudge` scorer backed by an offline `FakeLLMClient` (no provider key needed).
- `packages/tokensurf/examples/deterministic_scorers.py`,
  `packages/tokensurf/examples/trajectory_scorers.py`,
  `packages/tokensurf/examples/reference_scorer.py` — worked examples of the other three scorer
  families, all offline. `tokensurf init` does not copy these; it generates its own separate
  starter files (`evals/example_deterministic.py`, `evals/example_llm_judge.py`,
  `evals/test_agent_quality.py`, and a `README.md`), inline-templated rather than copied from
  this directory.
- [Self-hosting](self-hosting.md) — production server setup: secrets encryption, quality gates,
  notification channels, and Docker deployment.
