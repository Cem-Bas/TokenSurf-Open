# CLI reference

TokenSurf ships one CLI, `tokensurf`. When both the `tokensurf` and `tokensurf-server` packages are
installed in the same environment (the default for `uv sync` at the repo root, and inside the
server's Docker image), `tokensurf` also gains a `server` command group with the self-hosted
server's admin commands — migrations, projects, keys, users, gates, channels, and secrets. If only
`tokensurf` is installed (e.g. a CI job that only runs evals), the `server` group is simply absent
from `tokensurf --help`.

The packages are not published to PyPI. Install from source (clone the repo, then `uv sync`) and
invoke the CLI through `uv run` from the repository root:

```bash
uv run tokensurf --help
uv run tokensurf init my-tests                                          # scaffold a starter project
uv run tokensurf eval run FILE                                          # run an eval
uv run --directory packages/tokensurf-server tokensurf server migrate   # admin: run migrations (only if tokensurf-server installed)
```

`uv run --directory <pkg>` changes into that package directory before running, which also puts the
server CLI next to `alembic.ini` — required for `tokensurf-server migrate`. The examples below show
the bare command names; prefix them with the matching `uv run --directory` invocation.

## tokensurf — evaluation CLI

Typer app with one command group, `eval` ("Run and report agent evaluations."). There is no
standalone `push` command — pushing to a server happens as part of `tokensurf eval run`.

### tokensurf eval run

```bash
tokensurf eval run FILE [--output PATH] [--server URL] [--key KEY] [--label TEXT] [--no-config-pull]
```

Runs the evaluation defined in `FILE`, prints a console table, and writes per-case results to a
JSONL file. When both a server URL and an API key are available, it also pulls judge keys from the
server before the run and pushes the finished report to the server.

#### The eval file contract

`FILE` is a plain Python file that must define three module-level names:

| Name      | Type                        | Meaning                                           |
| --------- | --------------------------- | ------------------------------------------------- |
| `task`    | callable                    | Called once per case with the case input.         |
| `data`    | `Dataset`                   | The cases to run (see `Dataset.from_jsonl` etc.). |
| `scorers` | `list[Scorer]`              | Scorers applied to every case (see [Scorers](scorers.md)). |

```python
# eval_smoke.py
import tokensurf as ts

def task(question):
    return my_agent(question)  # your agent code

data = ts.Dataset.from_jsonl("cases.jsonl")
scorers = [ts.ExactMatch(), ts.LatencyUnder(seconds=2.0)]
```

If any of the three names is missing, the command prints an error and exits with code 1.

#### Arguments and options

| Argument / flag    | Default          | Env var fallback       | Description                                      |
| ------------------ | ---------------- | ---------------------- | ------------------------------------------------ |
| `FILE`             | required         | —                      | Python file exposing `task`, `data`, `scorers`.  |
| `--output`, `-o`   | `results.jsonl`  | —                      | JSONL results path.                              |
| `--server`         | none             | `TOKENSURF_SERVER_URL` | TokenSurf Server base URL.                       |
| `--key`            | none             | `TOKENSURF_API_KEY`    | Project ingest API key.                          |
| `--label`          | none             | —                      | Human-readable run label (e.g. branch or sha).   |
| `--no-config-pull` | off              | —                      | Skip pulling judge keys from the server.         |

Server behavior (only when both `--server` and `--key` are set, via flag or env var):

- Config pull (unless `--no-config-pull`): fetches the project's judge keys from
  `GET {server}/api/v1/config` and exports them as provider env vars — `openai` →
  `OPENAI_API_KEY`, `anthropic` → `ANTHROPIC_API_KEY`, `gemini` → `GEMINI_API_KEY`. A variable
  already set in your local environment is never overwritten (local env wins).
- Push: after the eval, the report is sent to `POST {server}/api/v1/runs` and the CLI echoes
  `Pushed run <run_id> to project '<project>' (pass_rate=..., n_cases=...)`.
- Both steps use `httpx`, provided by the `tokensurf[push]` extra (already present in a `uv sync`
  dev checkout).

#### Exit codes

| Code | Condition                                                                          |
| ---- | ---------------------------------------------------------------------------------- |
| 0    | Eval completed and results were written (and pushed, if a server was configured).   |
| 1    | `FILE` not found; `FILE` missing `task`/`data`/`scorers`; config pull failed; push failed. |

A `FILE` that exists but raises on import (for example a syntax error) is not caught: the
exception propagates as an uncaught traceback with a nonzero exit rather than a tidy `Error: ...`
message.

Note that failing or errored cases do not change the exit code — the run still exits 0. To fail CI
on quality, use `assert_eval` in a pytest test, or configure quality gates on the server.

#### Example

```bash
export TOKENSURF_SERVER_URL=https://tokensurf.internal
export TOKENSURF_API_KEY=tsk_...
uv run --directory packages/tokensurf tokensurf eval run eval_smoke.py -o smoke.jsonl --label "$(git rev-parse --short HEAD)"
```

Because `uv run --directory` changes into `packages/tokensurf` first, relative `FILE` and `-o`
paths resolve inside that package directory, not the directory you ran the command from. Pass
absolute paths (e.g. `"$PWD/eval_smoke.py" -o "$PWD/smoke.jsonl"`) to keep files where you are.

### tokensurf eval report

```bash
tokensurf eval report PATH
```

Pretty-prints a saved results file produced by `eval run`.

| Argument | Default  | Description                      |
| -------- | -------- | -------------------------------- |
| `PATH`   | required | Path to a `results.jsonl` file.  |

Prints `Cases: N`, then one line per score: case id, scorer name, status (`PASS`, `FAIL`, or
`ERROR` when the scorer itself errored), and the numeric value (three decimals, or `n/a`). Exits 1
if `PATH` does not exist.

```bash
uv run --directory packages/tokensurf tokensurf eval report smoke.jsonl
```

```text
Cases: 2
  c1         ExactMatch       PASS   1.000
  c1         LatencyUnder     PASS   1.000
  c2         ExactMatch       FAIL   0.000
  c2         LatencyUnder     PASS   1.000
```

## tokensurf-server — admin CLI

Typer app (`TokenSurf Server admin`) for operating a self-hosted server instance. Every command
needs `DATABASE_URL` set (the same database the server uses). `create-channel` and `create-secret`
additionally need `TOKENSURF_SECRET_KEY`, because they encrypt values at rest. All `create-*`
commands that take a project slug exit 1 if the project does not exist.

The admin CLI is exposed two ways: as the standalone `tokensurf-server` console script (available
whenever the `tokensurf-server` package is installed, even without `tokensurf`), and — when both
packages are installed — as the `tokensurf server` command group described above. Either way,
`python -m tokensurf_server.admin_cli` is not supported (the module has no `__main__` entry point
and exits silently without running anything).

### migrate

```bash
tokensurf-server migrate
```

No arguments. Runs `alembic upgrade head` as a subprocess, so it must run from the
`packages/tokensurf-server` directory (where `alembic.ini` lives) — `uv run --directory` does this
for you. Run it once before first boot and after every upgrade.

```bash
uv run --directory packages/tokensurf-server tokensurf-server migrate
```

### create-project

```bash
tokensurf-server create-project NAME [--slug TEXT]
```

| Argument / flag | Default  | Description                                                        |
| --------------- | -------- | ------------------------------------------------------------------ |
| `NAME`          | required | Display name of the project.                                       |
| `--slug`        | derived  | URL-safe slug; if omitted, derived from the lowercased name (runs of characters outside `a-z0-9-` become `-`, and leading/trailing hyphens are stripped — `"(Support Bot)"` yields `support-bot`). |

Prints `id=<id> slug=<slug>`.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-project "Support Bot" --slug support-bot
```

### create-key

```bash
tokensurf-server create-key PROJECT_SLUG [--label TEXT]
```

| Argument / flag | Default  | Description                            |
| --------------- | -------- | -------------------------------------- |
| `PROJECT_SLUG`  | required | Slug of the project the key belongs to.|
| `--label`       | `""`     | Human-readable label for this key.     |

Mints a project ingest API key (`tsk_` prefix) and prints the raw key exactly once. Only a SHA-256
hash and an 11-character display prefix are stored — the raw key cannot be recovered later, so
capture it immediately; if lost, mint a new one.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-key support-bot --label "ci"
```

### create-user

```bash
tokensurf-server create-user EMAIL [--password TEXT]
```

| Argument / flag | Default  | Description                                                    |
| --------------- | -------- | -------------------------------------------------------------- |
| `EMAIL`         | required | Login email for the dashboard user.                            |
| `--password`    | prompted | If omitted, you are prompted interactively with hidden input.  |

Creates a dashboard user with a hashed password (plaintext is never stored) and prints
`user <email> created`. Exits 1 if the email is already taken.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-user admin@example.com
# Password: (hidden prompt)
```

### create-gate

```bash
tokensurf-server create-gate PROJECT_SLUG NAME METRIC THRESHOLD [--comparison TEXT] [--scorer TEXT]
```

| Argument / flag | Default  | Description                                                              |
| --------------- | -------- | ------------------------------------------------------------------------ |
| `PROJECT_SLUG`  | required | Slug of the project.                                                     |
| `NAME`          | required | Gate name shown in the dashboard and notifications.                      |
| `METRIC`        | required | `pass_rate`, `mean_score`, or `scorer_pass_rate`.                        |
| `THRESHOLD`     | required | Float the metric is compared against.                                    |
| `--comparison`  | `gte`    | `lt`, `lte`, `gt`, or `gte`. The gate passes when `actual <comparison> threshold` holds. |
| `--scorer`      | `""`     | Scorer name (required for the `scorer_pass_rate` metric).                |

Inserts a quality gate and prints the gate id. While enabled (the default for CLI-created gates),
the gate is evaluated against every run pushed to the project; disabled gates are skipped.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-gate support-bot "min pass rate" pass_rate 0.9
```

### create-channel

```bash
tokensurf-server create-channel PROJECT_SLUG NAME SECRET [TO] --type TYPE
```

| Argument / flag | Default  | Description                                                        |
| --------------- | -------- | ------------------------------------------------------------------ |
| `PROJECT_SLUG`  | required | Slug of the project.                                               |
| `NAME`          | required | Channel name.                                                      |
| `SECRET`        | required | Channel secret, encrypted at rest. For `slack` and `webhook` this is the webhook URL. |
| `TO`            | `""`     | Recipient address (used by the `email` type).                      |
| `--type`        | required | `slack`, `webhook`, or `email`.                                    |

Creates a notification channel that fires when a run breaches a gate, and prints the channel id.
Email delivery uses the server's `TOKENSURF_SMTP_*` settings and sends to `TO`. Requires
`TOKENSURF_SECRET_KEY` to encrypt the secret.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-channel support-bot "eng alerts" \
  "https://hooks.slack.com/services/T000/B000/XXXX" --type slack
```

### create-secret

```bash
tokensurf-server create-secret PROJECT_SLUG PROVIDER SECRET
```

| Argument       | Default  | Description                                              |
| -------------- | -------- | -------------------------------------------------------- |
| `PROJECT_SLUG` | required | Slug of the project.                                     |
| `PROVIDER`     | required | Provider name, e.g. `openai`, `anthropic`, `gemini`.     |
| `SECRET`       | required | The provider API key, stored encrypted.                  |

Stores an encrypted judge/provider key for the project (upsert — one secret per provider) and
prints `secret set for <provider>`. These are the keys `tokensurf eval run` pulls via config pull
and exports as provider env vars. Requires `TOKENSURF_SECRET_KEY`.

```bash
uv run --directory packages/tokensurf-server tokensurf-server create-secret support-bot openai sk-...
```
