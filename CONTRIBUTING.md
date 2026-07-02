# Contributing

TokenSurf is an open-source AI-agent-quality framework: a scoring engine, capture SDK, and offline
eval harness (`tokensurf`), plus a self-hosted FastAPI + Postgres collector (`tokensurf-server`).
This page covers everything you need to build, test, and submit a change.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Python | >= 3.11 | Both packages (`requires-python = ">=3.11"`) |
| [uv](https://docs.astral.sh/uv/) | recent | Workspace sync, running tests and tools |
| PostgreSQL | 16 | `tokensurf-server` tests only |
| Docker (optional) | any recent | Easiest way to get Postgres 16 |

The packages are not published to PyPI. You work from source: clone the repo, then `uv sync`.

You only need Postgres when touching the server package. The repo-root `docker-compose.yml`
provides one (service name `db`):

```bash
docker compose up -d db
# Postgres 16 on localhost:5432, user tokensurf, password changeme, database tokensurf
```

These are placeholder dev credentials — fine for local tests, never for anything reachable from
outside your machine.

## Repository layout

The repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/): the root
`pyproject.toml` contains only `[tool.uv.workspace]` with `members = ["packages/*"]`, and a single
`uv.lock` pins the whole tree.

```text
packages/tokensurf/          # library: scoring engine, capture SDK, eval harness, CLI
  src/tokensurf/
  tests/
  examples/quickstart_eval.py
packages/tokensurf-server/   # self-hosted FastAPI + Postgres collector
  src/tokensurf_server/
  migrations/                # Alembic env + versions/ (alembic.ini sits next to it at the package root)
  tests/
docker-compose.yml           # dev stack: Postgres 16 + server
docs/                        # user documentation (MkDocs sources)
.github/workflows/ci.yml     # the CI gates described below
```

`tokensurf-server` depends on `tokensurf` via `[tool.uv.sources] tokensurf = { workspace = true }`,
so library changes are immediately visible to the server package — no reinstall step.

## Development setup

```bash
git clone <repo-url>
cd TokenSurf
uv sync
```

`uv sync` resolves the whole workspace into a shared `.venv` at the repo root. To include a
package's optional extras (e.g. `httpx` for push):

```bash
uv sync --directory packages/tokensurf --extra reference --extra push
```

## Running tests

### Library (`packages/tokensurf`)

No services needed:

```bash
uv run --directory packages/tokensurf pytest
```

### Server (`packages/tokensurf-server`)

Server tests hit a real Postgres. Start one (`docker compose up -d db`), then:

```bash
DATABASE_URL="postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf" \
TOKENSURF_SECRET_KEY=test-secret-key \
uv run --directory packages/tokensurf-server pytest
```

Notes on the environment:

| Variable | Why the tests need it |
| --- | --- |
| `DATABASE_URL` | Test engine target. `tests/conftest.py` falls back to the compose-stack URL above if unset, so with the default stack you can omit it. |
| `TOKENSURF_SECRET_KEY` | Fernet passphrase for `crypto.py`. Two suites (`test_audit_service.py` and `test_secrets_service.py`) require it in the environment; `test-secret-key` is the conventional test value. |
| `TOKENSURF_ALLOW_INSECURE_SESSION_SECRET` | Set to `1` automatically by `tests/conftest.py` so the startup guard tolerates the built-in default session secret during tests. Never set it in production. |

Ordinary DB tests are non-destructive: the `db_session` fixture binds each test to a connection
with an open outer transaction and `join_transaction_mode="create_savepoint"`, so even
application-level `session.commit()` calls only commit a savepoint, and everything rolls back at
teardown.

### `TOKENSURF_DESTRUCTIVE_DB_TESTS`

The migration tests (`tests/test_migrations*.py`) are the exception: they verify the Alembic chain
by dropping **every table** in `DATABASE_URL` and upgrading from an empty schema. The savepoint
trick cannot isolate that, so they are skipped unless you opt in:

```bash
DATABASE_URL="postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf" \
TOKENSURF_SECRET_KEY=test-secret-key \
TOKENSURF_DESTRUCTIVE_DB_TESTS=1 \
uv run --directory packages/tokensurf-server pytest tests/test_migrations.py
```

Only set the flag against a throwaway database. CI sets it because its Postgres service container
is ephemeral.

## Lint and type gates

CI (`.github/workflows/ci.yml`) runs all three gates per package and every one must be clean —
zero ruff findings, zero pyright errors:

```bash
uv run --directory packages/tokensurf ruff check .
uv run --directory packages/tokensurf ruff format --check .
uv run --directory packages/tokensurf pyright

uv run --directory packages/tokensurf-server ruff check .
uv run --directory packages/tokensurf-server ruff format --check .
uv run --directory packages/tokensurf-server pyright
```

Configuration lives in each package's `pyproject.toml`: ruff line length 100, target `py311`, rule
sets `E, F, I, UP, B`; pyright in `standard` mode over `src` and `tests`. Run
`uv run ruff format .` (without `--check`) to auto-format before committing.

Tests are a CI gate too: each job runs its package's pytest suite (the library job with coverage,
and it also executes `examples/quickstart_eval.py`).

## Database migrations

Alembic lives under `packages/tokensurf-server/` (`alembic.ini` + `migrations/`). The revision
chain is strictly linear — no branches, no merge revisions:

```text
0001_initial -> 0002_users -> 0003_gates_channels -> 0004_project_secrets -> 0005_audit_logs (head)
```

To add a schema change:

1. Create a new file under `packages/tokensurf-server/migrations/versions/` named
   `NNNN_short_description.py`, with `revision = "NNNN"` and `down_revision` set to the current
   head — keep the chain linear.
2. Write both `upgrade()` and `downgrade()`.
3. Add a matching migration test following the existing `tests/test_migrations*.py` pattern,
   gated on `TOKENSURF_DESTRUCTIVE_DB_TESTS`.
4. Apply locally with the admin CLI, which runs `alembic upgrade head`:

```bash
DATABASE_URL="postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf" \
uv run --directory packages/tokensurf-server tokensurf-server migrate
```

## Test-driven development

This repo follows a failing-test-first convention: write the test that captures the desired
behavior, watch it fail, then write the implementation that makes it pass. Bug fixes must include
a regression test that fails on the unfixed code. Every change lands with its tests.

## Commit style

Conventional-commit-ish subjects: `type(scope): imperative summary`. Scopes follow the code area
(`core`, `scorers`, `sdk`, `eval`, `cli`, `server`, ...). Examples from the log:

```text
feat(core): add ScoreResult model with errored() factory
feat(core): add Trace model with duration and spans_of
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.

## Security-sensitive areas

Some modules guard secrets or authentication and need extra care — smaller diffs, tests for the
failure paths, and an explicit call-out in your PR description:

| Area | Files (under `packages/tokensurf-server/src/tokensurf_server/`) |
| --- | --- |
| Secret encryption at rest | `crypto.py` (Fernet key derived from `TOKENSURF_SECRET_KEY`) |
| Ingest API-key auth | `ingest.py` (Bearer-key `get_project` dependency and key hashing) |
| CSRF protection | `web/csrf.py` and the `_require_csrf` checks in `web/routes.py` |
| Provider/judge secrets | `secrets_service.py` |

Hard rules:

- Never log, print, or store secret values in plaintext. Audit records carry only metadata such as
  provider names and key counts — never the keys themselves.
- `GET /api/v1/config` is the only endpoint that returns decrypted secrets; it must keep its
  `Cache-Control: no-store` response header.
- Do not weaken the startup guard around the default session secret or widen any of the insecure
  test-only environment overrides.

## License and sign-off

TokenSurf is licensed under [Apache-2.0](LICENSE). By contributing, you agree that your
contributions are licensed under the same terms. A DCO-style `Signed-off-by:` trailer
(`git commit -s`) is welcome but not required.
