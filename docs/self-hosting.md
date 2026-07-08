# Self-hosting the server

TokenSurf Server is the self-hosted collector for eval runs: a FastAPI + Postgres service with an
ingest API (`/api/v1`) and a login-protected dashboard. It runs entirely inside your own
infrastructure — this page covers both ways to run it, first-run configuration, bootstrapping via
the admin CLI, and what to change for production.

TokenSurf is not yet published to PyPI; everything below runs from a clone of the repository.

## Quick start with Docker Compose

The repository root ships a `docker-compose.yml` that starts Postgres 16 plus the server:

```bash
git clone <your-clone-url> tokensurf && cd tokensurf
docker compose up
```

The stack provides:

- `db` — `postgres:16` with a named volume (`postgres_data`), exposed on `localhost:5432`, with a
  `pg_isready` healthcheck the app waits on.
- `app` — built from `packages/tokensurf-server/Dockerfile`, exposed on `localhost:8000`. The
  container runs migrations (`tokensurf-server migrate`) and then starts
  `uvicorn tokensurf_server.app:app --host 0.0.0.0 --port 8000` on every start.

The stack boots as-is, but every credential in it is a **dev placeholder**. Before any non-local
use, change each `changeme` value in the `db` and `app` services:

```yaml
  app:
    environment:
      DATABASE_URL: postgresql+psycopg://tokensurf:changeme@db:5432/tokensurf  # change me
      TOKENSURF_SESSION_SECRET: "<random string, at least 32 characters>"      # change me
      TOKENSURF_SECRET_KEY: "<random passphrase for secret encryption>"       # change me
```

The session secret must stay at least 32 characters — the app refuses to start otherwise (see
[Required first-run environment](#required-first-run-environment)). Generate strong values with:

```bash
openssl rand -hex 32
```

Once up: the dashboard is at `http://localhost:8000/login`, the ingest API under
`http://localhost:8000/api/v1`, Swagger UI at `/api/docs`, and a health check at `/healthz`.

## Running manually

To run against an existing Postgres instead of the compose stack, you need Python 3.11+,
[uv](https://docs.astral.sh/uv/), and a reachable Postgres database.

```bash
git clone <your-clone-url> tokensurf && cd tokensurf/packages/tokensurf-server
uv sync

export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db"
export TOKENSURF_SESSION_SECRET="$(openssl rand -hex 32)"   # persist this — see note below
export TOKENSURF_SECRET_KEY="<random passphrase>"

uv run tokensurf-server migrate
uv run uvicorn tokensurf_server.app:app --host 0.0.0.0 --port 8000
```

Notes:

- Run `migrate` from `packages/tokensurf-server` (it shells out to `alembic upgrade head`, and
  `alembic.ini` lives in that directory). Alembic reads `DATABASE_URL` from the same settings as
  the app.
- The server also loads a `.env` file from its working directory, so you can put the exports
  above in `packages/tokensurf-server/.env` instead. Keep that file out of version control.
- The `HOST` and `PORT` settings exist but are not consumed by an in-repo entrypoint — the bind
  address and port are whatever you pass to `uvicorn` (`--host` / `--port`).
- Don't regenerate `TOKENSURF_SESSION_SECRET` on every start: session cookies are signed with it,
  so changing it invalidates all dashboard logins.

## Required first-run environment

Two secrets matter before the first run:

- `TOKENSURF_SESSION_SECRET` — signs dashboard session cookies and CSRF tokens. At startup the
  app validates it and **refuses to start** (a `RuntimeError` in the lifespan) if it is still the
  built-in default or shorter than 32 characters. The only bypass is the test-only
  `TOKENSURF_ALLOW_INSECURE_SESSION_SECRET=1` flag — never set it in production.
- `TOKENSURF_SECRET_KEY` — passphrase used to derive (via SHA-256) the Fernet key that encrypts
  notification-channel secrets and project provider keys at rest. It is not checked at startup,
  but any operation that encrypts or decrypts a secret — `create-channel`, `create-secret`,
  saving a channel or provider key from the settings pages, and `GET /api/v1/config` — raises
  `SecretKeyMissing` without it (viewing the settings page only lists provider names and does not
  decrypt anything). Secrets are never silently stored as plaintext. Set it before first run and
  treat it as long-lived: data encrypted under one passphrase cannot be decrypted without it.

`DATABASE_URL` is also required — the app fails loudly at startup (a pydantic `ValidationError`)
when it is missing.

## Bootstrapping with the admin CLI

The fastest way to bootstrap a fresh install is the **web setup wizard**: start the server, then
visit `http://<host>:<port>/setup`. While no dashboard user exists yet, every page redirects here
automatically. The server prints the setup-token *file path* to its startup logs (default
`./tokensurf_setup_token`, configurable via `TOKENSURF_SETUP_TOKEN_PATH`) — not the token itself, so
the raw token never lands in log aggregation. Read the token from that file and paste it into the
setup form; this proves you're the operator (with filesystem access), not whoever else reaches the
port first. Once the first admin account is created, `/setup` stops being reachable (it redirects to
`/login`) for good.

![The first-run setup wizard asking for the setup token, admin email, and password](images/setup-wizard.png)

For scripted/headless installs, the admin CLI below does the same thing non-interactively:

The server package installs a `tokensurf-server` console script (a Typer app). A fresh install
needs four commands:

```bash
cd packages/tokensurf-server
uv run tokensurf-server migrate                              # alembic upgrade head
uv run tokensurf-server create-user you@example.com          # prompts for a password
uv run tokensurf-server create-project "My Agent"            # prints id=<id> slug=my-agent
uv run tokensurf-server create-key my-agent --label ci       # prints the raw API key
```

`create-key` prints the raw ingest key (a `tsk_`-prefixed token) **exactly once** — the server
stores only its SHA-256 hash and an 11-character display prefix. Copy it immediately; if you lose
it, mint a new key.

Under Docker Compose, migrations already ran at container start, so bootstrap with:

```bash
docker compose exec app uv run tokensurf-server create-user you@example.com
docker compose exec app uv run tokensurf-server create-project "My Agent"
docker compose exec app uv run tokensurf-server create-key my-agent --label ci
```

Then sign in at `http://localhost:8000/login` with the user you created, and push runs from your
eval suite:

```bash
tokensurf eval run eval.py --server http://localhost:8000 --key tsk_...
```

### Admin CLI reference

| Command | Arguments | Notes |
| --- | --- | --- |
| `migrate` | — | Runs `alembic upgrade head`. |
| `create-project NAME` | `--slug` | Slug derived from the name if omitted; prints `id=<id> slug=<slug>`. |
| `create-key PROJECT_SLUG` | `--label` | Mints an ingest API key; prints the raw key once, stores only hash + prefix. |
| `create-user EMAIL` | `--password` (prompted, hidden) | Creates a dashboard user; password stored as a PBKDF2 hash. Exits 1 if the email is taken. |
| `create-gate PROJECT_SLUG NAME METRIC THRESHOLD` | `--comparison lt\|lte\|gt\|gte`, `--scorer` | Metric is `pass_rate`, `mean_score`, or `scorer_pass_rate` (`--scorer` required for the last). |
| `create-channel PROJECT_SLUG NAME SECRET [TO]` | `--type slack\|webhook\|email` (required) | Secret encrypted at rest; `TO` is the recipient for the email type. |
| `create-secret PROJECT_SLUG PROVIDER SECRET` | — | Stores an encrypted judge/provider key (upsert per provider), served to eval runs by `GET /api/v1/config`. See [Scorers](scorers.md) for the LLM judge that uses these keys. |

Gates, channels, and provider secrets can also be managed from the dashboard's settings pages.

## Migrations

`tokensurf-server migrate` is the only migration command you need — it runs
`alembic upgrade head` against `DATABASE_URL`. The migration chain lives in
`packages/tokensurf-server/migrations/versions/`.

- Docker image: migrations run automatically on every container start (part of the image `CMD`),
  so `docker compose up` after pulling a new version is enough.
- Manual installs: run `uv run tokensurf-server migrate` from `packages/tokensurf-server` after
  every upgrade, before restarting uvicorn.

## Environment variable reference

Settings are read from the process environment and from a `.env` file in the server's working
directory (unknown variables are ignored).

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | — | SQLAlchemy connection URL used by the app and Alembic, e.g. `postgresql+psycopg://user:pass@host:5432/db`. Startup fails if unset. |
| `TOKENSURF_SESSION_SECRET` | in practice (startup guard rejects the default) | `tokensurf-dev-secret-change-me` | Signs session cookies and CSRF tokens. The app refuses to start with the default or any value under 32 characters. |
| `TOKENSURF_SECRET_KEY` | for secrets | unset | Passphrase (SHA-256 → Fernet key) encrypting channel secrets and provider keys at rest. Required for any secret write/read; raises `SecretKeyMissing` otherwise. |
| `TOKENSURF_SETUP_TOKEN_PATH` | no | `./tokensurf_setup_token` | Path to the first-run setup-token file (see Bootstrapping). |
| `TOKENSURF_CONFIG_RATE_LIMIT` | no | `30/60` | Per-project rate limit for `GET /api/v1/config`, as `count/window_seconds`. Exceeding it returns 429 with a `Retry-After` header. A count of 0 or below disables the limiter. Fixed at module import — setting it after the process starts has no effect; restart to change. |
| `HOST` | no | `0.0.0.0` | Declared in settings but not consumed by an in-repo entrypoint; set the bind host with `uvicorn --host`. |
| `PORT` | no | `8000` | Same as `HOST`; set the port with `uvicorn --port`. |
| `TOKENSURF_SMTP_HOST` | no | unset | SMTP host for email notification channels. |
| `TOKENSURF_SMTP_PORT` | no | `587` | SMTP port. |
| `TOKENSURF_SMTP_USER` | no | unset | SMTP username. |
| `TOKENSURF_SMTP_PASSWORD` | no | unset | SMTP password. |
| `TOKENSURF_SMTP_FROM` | no | unset | From address for email notifications. |
| `TOKENSURF_ALLOW_INSECURE_SESSION_SECRET` | test-only | unset | Bypasses the session-secret startup guard when set to `1`, `true`, `yes`, or `on` (case-insensitive). Any other value — including `0` and `false` — is treated as off. For local development and the test suite only; never set in production. |
| `TOKENSURF_DESTRUCTIVE_DB_TESTS` | test-only | unset | Read only by the test suite, never by the server. Set `=1` against a throwaway database to enable migration tests that drop every table in `DATABASE_URL`. |

The `.env.example` at the repository root configures the eval/SDK side (provider API keys for
local `tokensurf eval` runs), not the server.

## Production notes

- **TLS is required.** Ingest API keys travel as `Authorization: Bearer` headers, the dashboard
  uses signed session cookies, and `GET /api/v1/config` returns decrypted provider keys (with
  `Cache-Control: no-store`). Terminate TLS at a reverse proxy in front of uvicorn; never expose
  the server over plain HTTP beyond localhost.
- **Rate limiting is in-process.** The `GET /api/v1/config` limiter is a per-process sliding
  window keyed by project: it resets on restart, and with multiple uvicorn workers each worker
  keeps its own counter, so the effective limit scales with the worker count. In multi-worker or
  multi-instance deployments, enforce an additional rate limit at the gateway/reverse proxy —
  and consider covering `POST /login` and the rest of `/api/v1` there too.
- **Cap request bodies at the proxy.** The app does not enforce a request body-size limit on
  `POST /api/v1/runs`; body-size limiting is intentionally deferred to the reverse proxy (e.g.
  `client_max_body_size` in nginx).
- **Back up Postgres.** All state — runs, users, hashed API keys, gates, channels, encrypted
  secrets, and audit logs — lives in the database. For the compose stack, that is the
  `postgres_data` volume.
- **Guard your keys.** Losing `TOKENSURF_SECRET_KEY` makes every stored channel secret and
  provider key unrecoverable; rotating `TOKENSURF_SESSION_SECRET` signs everyone out. Store both
  in your secret manager alongside the database credentials.
- **Know your unauthenticated surface.** `/healthz` (use it for load-balancer checks), `/static`,
  the login page, and the Swagger UI at `/api/docs` respond without authentication. Everything
  else requires a session cookie (dashboard) or a Bearer API key (`/api/v1`), with two footnotes:
  `POST /logout` is sessionless but CSRF-verified, and the OpenAPI schema (`/openapi.json`)
  backing the Swagger UI is also unauthenticated.
