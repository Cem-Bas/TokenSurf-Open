# Judge keys & config pull

Scorers like `LLMJudge` need provider API keys (OpenAI, Anthropic, Gemini) at eval time. Instead of
copying those keys into every CI system, you store them once on your TokenSurf Server — encrypted at
rest — and let CI pull them at the start of each eval run.

```bash
# CI needs exactly two values: the server URL and the project's ingest key.
export TOKENSURF_SERVER_URL=https://tokensurf.internal
export TOKENSURF_API_KEY=tsk_your_project_key

tokensurf eval run eval.py --label "$GIT_BRANCH"
# 1. pulls judge keys from the server and exports them as provider env vars
# 2. runs the eval
# 3. pushes the report back to the same server
```

## Storing keys on the server

Keys are stored per project, one row per provider, and are upserted by provider — saving a key for
a provider that already has one overwrites it, so you rotate a key by simply saving it again.

### Settings UI

On your server's dashboard, open **Settings → your project → Add Key**. Pick a provider
(`openai`, `anthropic`, `gemini`, or `other`) and paste the key into the API Key field.

The field is write-only: it is a password input, and once saved the dashboard only ever shows
`•••• set` next to the provider name — the value is never displayed back. To replace a key, save a
new value for the same provider; to remove it, use **Delete**.

### Admin CLI

On the server host, use the `tokensurf-server` admin CLI:

```bash
uv run tokensurf-server create-secret my-agent openai sk-...
# secret set for openai
```

Arguments are positional: `create-secret <PROJECT_SLUG> <PROVIDER> <SECRET>`. It upserts by
provider, exactly like the Settings UI, and exits with code 1 if the project slug does not exist.

### Encryption at rest

Secrets are encrypted with Fernet (symmetric authenticated encryption) before they touch the
database. The Fernet key is derived from the `TOKENSURF_SECRET_KEY` environment variable via
SHA-256, so any string works as the passphrase. Plaintext is never stored.

If `TOKENSURF_SECRET_KEY` is unset, any attempt to store or read a secret raises
`SecretKeyMissing` — the server never falls back to storing plaintext, and a decrypt with a
missing key fails the whole request rather than returning partial results.

## The config endpoint

`GET /api/v1/config` is the single endpoint where secrets leave the server. It authenticates with
the project's ingest key as a bearer token and returns the decrypted judge keys for that project:

```bash
curl -H "Authorization: Bearer tsk_your_project_key" \
  https://tokensurf.internal/api/v1/config
```

```json
{"judge_keys": {"openai": "sk-...", "anthropic": "sk-ant-..."}}
```

| Property | Behavior |
|---|---|
| Auth | `Authorization: Bearer <ingest key>`; 401 on missing, malformed, empty, or unknown key |
| Response | `{"judge_keys": {"<provider>": "<plaintext key>", ...}}` |
| Caching | `Cache-Control: no-store` is always set — proxies, CDNs, and browsers must not cache it |
| Rate limit | Per project, sliding window; over the limit returns 429 with a `Retry-After` header |
| Audit | Every pull records a `config.pull` audit row (see below) |

### Rate limiting

Pulls are rate-limited per project via the `TOKENSURF_CONFIG_RATE_LIMIT` environment variable,
formatted as `count/window_seconds`. The default is `30/60` — 30 requests per 60 seconds. When the
limit is exceeded the server returns `429` with a `Retry-After` header giving the number of
seconds to wait. A count of `0` (or negative) disables the limiter.

The limiter is in-process and read once at server start: it resets on restart, does not share
state across multiple workers, and changing the env var requires a restart. In multi-worker
deployments, add an additional rate limit at your reverse proxy.

## Pulling from Python

`fetch_config()` lives in `tokensurf.sdk.config` and needs `httpx`, provided by the optional
`push` extra (in a source checkout, `uv sync` already installs it; the packages are not yet on
PyPI, so install from a clone):

```python
from tokensurf.sdk.config import ConfigError, fetch_config

config = fetch_config(server_url="https://tokensurf.internal", api_key="tsk_...")
judge_keys = config["judge_keys"]  # {"openai": "sk-...", ...}
```

```python
def fetch_config(*, server_url: str, api_key: str, timeout: float = 30.0) -> dict
```

All parameters are keyword-only. Any non-2xx response raises `ConfigError` with the status code
and the first 200 characters of the response body; the error is never swallowed, so a failed pull
surfaces immediately.

## Pulling from the CLI

`tokensurf eval run` pulls config automatically whenever both `--server` and `--key` are set
(flags or their env vars) and `--no-config-pull` is not passed. The pull happens before the eval
runs, so judge scorers see the keys.

| Flag | Env var | Default | Purpose |
|---|---|---|---|
| `--server` | `TOKENSURF_SERVER_URL` | none | TokenSurf Server base URL |
| `--key` | `TOKENSURF_API_KEY` | none | Project ingest API key |
| `--no-config-pull` | — | off | Skip the config pull entirely |

Each pulled key is exported as the conventional provider env var:

| Provider | Env var set |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `gemini` | `GEMINI_API_KEY` |

Two rules to know:

- **Local env wins.** A provider env var is only set if it is not already present in the
  environment. An `OPENAI_API_KEY` exported in your CI job (or shell) is never overwritten by the
  server's value.
- **A failed pull fails CI.** On `ConfigError` (bad key, server down, rate-limited), the CLI
  prints `Config pull failed: ...` to stderr and exits with code 1 — the eval does not run against
  missing keys.

Keys stored under a provider outside the table above (the Settings UI's `other` option) are still
returned by `/api/v1/config`, but the CLI does not map them to an env var; consume them with
`fetch_config()` directly if you need them.

## Security notes

> **Blast radius of an ingest key.** The project ingest key is the bearer token for
> `/api/v1/config`, so it doubles as a config-read credential: anyone holding a project's ingest
> key can read that project's decrypted judge keys. Treat ingest keys with the same care as the
> provider keys behind them — scope one key per CI system, and rotate provider keys if an ingest
> key leaks. See [Security](security.md) for the full trust model.

Every pull is audited. Each successful `GET /api/v1/config` records a `config.pull` audit row with
the key prefix of the calling key (`api:tsk_xxxxxxx`), the client IP, and a key *count* — never
the key values themselves. Saving or deleting a key through the Settings UI records `secret.set` /
`secret.delete` rows the same way. The newest entries appear under **Recent Activity** on the
project's settings page, so an unexpected pull from an unfamiliar IP is visible at a glance.

## Server environment variables

| Env var | Default | Purpose |
|---|---|---|
| `TOKENSURF_SECRET_KEY` | unset | Passphrase for Fernet encryption of stored secrets; required to store or serve judge keys |
| `TOKENSURF_CONFIG_RATE_LIMIT` | `30/60` | Per-project pull limit as `count/window_seconds`; `0` disables |
