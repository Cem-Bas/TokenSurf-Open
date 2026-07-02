# Security model

TokenSurf Server is the self-hosted collector that receives eval runs from the TokenSurf SDK/CLI
and serves the dashboard. This page describes the trust boundary and every security mechanism in
the server, exactly as implemented, plus what you must handle at the deployment layer.

## Trust boundary

Everything runs inside your own infrastructure. The SDK and CLI talk only to the server URL you
give them; the server is a FastAPI app backed by your Postgres database. Provider API keys (the
"judge keys" used by LLM-based scorers — see [Scorers](scorers.md)) are stored encrypted in your
database and served only by your server to clients holding a valid project ingest key. There is no
managed service, no telemetry, and no external data path: your keys never leave your infra.

Two authentication schemes exist:

| Surface | Auth | Credential |
|---|---|---|
| Ingest API (`/api/v1/*`) | HTTP Bearer | Project ingest key (`tsk_...`), stored hashed |
| Dashboard (HTML pages) | Signed session cookie | Email + password, PBKDF2-hashed |

Unauthenticated endpoints: `GET /healthz`, the `/static` mount, `GET /login` / `POST /login`, the
Swagger UI at `/api/docs`, and its schema at `/openapi.json`.

## Security-relevant configuration

| Variable | Default | Purpose |
|---|---|---|
| `TOKENSURF_SESSION_SECRET` | insecure built-in default | Signs session cookies and CSRF tokens. Startup fails unless it is changed and is at least 32 characters. |
| `TOKENSURF_SECRET_KEY` | unset | Passphrase from which the Fernet encryption key for stored secrets is derived. |
| `TOKENSURF_CONFIG_RATE_LIMIT` | `30/60` | Rate limit for `GET /api/v1/config` as `count/window_seconds`. `0/...` disables. |
| `TOKENSURF_LOGIN_RATE_LIMIT` | `10/60` | Brute-force throttle for `POST /login` (per client IP and per account) as `count/window_seconds`. `0/...` disables. |
| `TOKENSURF_BLOCK_PRIVATE_WEBHOOKS` | `false` | When true, notification webhooks may not target loopback/private/reserved addresses (link-local/metadata literals are refused regardless). See Notification egress below. |
| `TOKENSURF_ALLOW_INSECURE_SESSION_SECRET` | unset | Local/test-only bypass of the session-secret guard. Only `1`, `true`, `yes`, or `on` count as set. |
| `TOKENSURF_SECURE_COOKIES` | `false` | When true, sets the `Secure` flag on the session and CSRF cookies (requires HTTPS). Turn it on in any TLS-terminated deployment. |
| `DATABASE_URL` | required | Postgres connection URL. Missing value fails loudly at startup. |

Generate strong values before first boot:

```bash
export TOKENSURF_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export TOKENSURF_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

## Secrets at rest

### Encrypted: channel secrets and judge keys

Two kinds of values are encrypted before they touch the database:

| Value | Table / column | Written by |
|---|---|---|
| Judge/provider API keys | `project_secrets.key_enc` | Settings UI, `tokensurf-server create-secret` |
| Notification channel secrets (Slack/webhook URLs, etc.) | `notification_channels.secret_enc` | Settings UI, `tokensurf-server create-channel` |

Encryption is symmetric Fernet (AES-CBC + HMAC, from the `cryptography` package). The Fernet key
is derived from `TOKENSURF_SECRET_KEY` so any arbitrary-length string works as the passphrase:

```python
# crypto.py — key derivation
Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
```

The failure mode is loud by design: if `TOKENSURF_SECRET_KEY` is unset, any attempt to encrypt or
decrypt raises `SecretKeyMissing` (a `RuntimeError`). Secrets are never silently stored or
returned as plaintext, and decryption never returns partial results — if the key is missing, the
whole call fails. Note this check runs at encrypt/decrypt time, not at startup: a server without
`TOKENSURF_SECRET_KEY` boots fine but fails as soon as a secret is written or read.

### Hashed: ingest keys and passwords

Values the server only ever needs to *verify* are hashed one-way, never encrypted:

| Value | Scheme | Details |
|---|---|---|
| Ingest API keys | SHA-256 hex digest | Key format `tsk_` + `secrets.token_urlsafe(32)`. Stored: digest + first 11 chars as a display prefix. Requests are resolved by an exact-match database lookup on the digest; a constant-time `verify_key` helper (`secrets.compare_digest`) is also provided. |
| Dashboard passwords | PBKDF2-HMAC-SHA256 | 240,000 iterations, fresh random 16-byte salt per hash. Stored as `pbkdf2$<iterations>$<salt_hex>$<dk_hex>`. Constant-time verification. |

The raw ingest key is printed exactly once, when `tokensurf-server create-key` mints it. It cannot
be recovered afterwards — losing it means minting a new key.

Login additionally verifies a precomputed dummy hash when the email does not exist, so a login
attempt does the same PBKDF2 work either way and response timing does not reveal which emails
have accounts.

## Secret egress: one endpoint only

`GET /api/v1/config` is the only place secrets leave the server, in any form. It returns the
project's decrypted judge keys so CI runners can score with `LLMJudge` without baking provider
keys into every pipeline:

```bash
curl -H "Authorization: Bearer tsk_your_project_key" \
  https://tokensurf.internal/api/v1/config
# {"judge_keys": {"openai": "sk-...", "anthropic": "..."}}
```

Controls on this endpoint:

- **Bearer auth**: the ingest key is resolved by hash; missing, malformed, empty, or unknown keys
  get a 401.
- **`Cache-Control: no-store`**: set on every response so proxies, CDNs, and browsers never cache
  plaintext keys.
- **Rate limit**: per project, `TOKENSURF_CONFIG_RATE_LIMIT` (default 30 requests per 60 seconds);
  excess requests get 429 with a `Retry-After` header.
- **Audit**: every pull is recorded as a `config.pull` event (see below).

Everywhere else, secrets are write-only:

- The settings UI accepts secrets through `<input type="password">` fields and lists only the
  provider name and whether a value exists — the ciphertext is never passed to templates (page
  queries map secret rows to `(provider, has_value)` view objects), and plaintext is never
  rendered.
- Secret-handling error paths log only the exception class name (`type(exc).__name__`), never
  messages that could embed a secret value, and never the value itself. (Failure paths that never
  touch secrets, such as gate evaluation and run ingest, may log full tracebacks.)

## Dashboard sessions

Sessions are signed cookies, not server-side sessions. On login the server sets `ts_session` to an
`itsdangerous` `URLSafeSerializer` token (signed with `TOKENSURF_SESSION_SECRET`, salt
`ts-session`) encoding the user id. The cookie is `HttpOnly` and `SameSite=Lax`. Incoming tokens
are checked against a strict URL-safe base64 character allowlist before signature verification, so
malformed bytes cannot be smuggled past the HMAC check. Invalid or tampered tokens resolve to no
user and redirect to `/login`.

The cookie sets the `Secure` flag when `TOKENSURF_SECURE_COOKIES=true` (enable it once you terminate
HTTPS); it is off by default so local HTTP development works. Serving the dashboard over HTTPS is
still your deployment's job (see the checklist below).

### Session-secret guard

The server refuses to start with a weak signing secret. At startup (ASGI lifespan),
`validate_security_config` raises `RuntimeError` when `TOKENSURF_SESSION_SECRET` is either the
built-in default (`tokensurf-dev-secret-change-me`) or shorter than 32 characters.

The check runs in the ASGI lifespan, so it only fires when the server is started normally
(uvicorn's default). Running with `--lifespan off` skips it — don't.

The only bypass is `TOKENSURF_ALLOW_INSECURE_SESSION_SECRET`, intended for local runs and tests.
It is parsed strictly: only `1`, `true`, `yes`, or `on` (case-insensitive, trimmed) enable it —
`0`, `false`, `no`, `off`, and the empty string do **not**, so an operator setting the flag to
`"0"` cannot accidentally disable the guard.

## CSRF protection

State-changing dashboard POSTs use a double-submit cookie scheme:

1. `CsrfMiddleware` runs site-wide: on every request it reuses the incoming `ts_csrf` cookie when
   its signature verifies — an invalid cookie (tampered, or signed with a rotated secret) is
   replaced with a fresh token, so a stale cookie self-heals on the next page load instead of
   permanently 403-ing every POST. The token is exposed to templates as
   `request.state.csrf_token`, and the `Set-Cookie` is re-emitted on every response.
2. Templates embed the token as a hidden `csrf_token` form field.
3. On POST, the server verifies that both the cookie token and the form token carry valid
   signatures (`URLSafeSerializer` with the session secret, salt `ts-csrf`) and encode the same
   random ID. Any missing, tampered, or mismatched token gets a 403.

The `ts_csrf` cookie is deliberately not `HttpOnly` (the double-submit pattern requires the page
to echo it); the token contains only a signed random ID, no session data. The middleware sets the
cookie only on HTML responses (`Content-Type: text/html`) — JSON endpoints (`/api/*`, `/healthz`,
`/openapi.json`) and static assets never carry it.

Double-submit resists a *foreign-origin* attacker (same-origin policy blocks reading the cookie, and
`SameSite=Lax` stops a cross-site POST from sending it). Its residual weakness is an attacker who can
*plant* a matching `ts_csrf` cookie — via a sibling/parent-domain cookie on a shared registrable
domain, or a network MITM injecting `Set-Cookie` over plain HTTP. Both are closed by serving over
HTTPS with `TOKENSURF_SECURE_COOKIES=true` (so the cookie can't be injected in transit) and by not
hosting the dashboard under a domain you share with untrusted subdomains. A future Origin/Referer
allowlist would remove the residual entirely.

CSRF-verified POSTs:

| Route |
|---|
| `POST /login` and `POST /logout` |
| `POST /settings/{slug}/gates` and `POST /settings/{slug}/gates/{gate_id}/delete` |
| `POST /settings/{slug}/channels`, `.../channels/{channel_id}/delete`, `.../channels/{channel_id}/test` |
| `POST /settings/{slug}/secrets` and `POST /settings/{slug}/secrets/{provider}/delete` |

`POST /login` is CSRF-protected too: the login page carries a token issued by the middleware, which
closes login CSRF (an attacker forcing a victim into an attacker-chosen session). The double-submit
still relies only on same-origin cookie access, so it does not weaken the credential check.

## Rate limiting

Two endpoints are throttled in-app by a thread-safe sliding-window limiter (stdlib only). Both
return 429 with a `Retry-After` header when exceeded, and both read their spec at process import.

- **`GET /api/v1/config`** — keyed by project id, `TOKENSURF_CONFIG_RATE_LIMIT` (default `30/60`).
- **`POST /login`** — throttled by BOTH the client IP and the submitted account, using
  `TOKENSURF_LOGIN_RATE_LIMIT` (default `10/60`). The per-account key means a distributed guess
  against one email (an attacker rotating source IPs) is still throttled, not just a single noisy
  IP. `0/...` disables it. The throttle runs after the CSRF check and before the credential check.

Caveats you must plan for:

- The limiters are **per process** and reset on restart. Running multiple uvicorn workers
  multiplies the effective limit by the worker count. In multi-worker deployments, enforce an
  additional rate limit at your gateway or reverse proxy.
- **Behind a reverse proxy, the login limiter keys on the proxy's IP** unless you enable
  trusted-proxy handling (uvicorn `--proxy-headers` with `--forwarded-allow-ips`, or equivalent).
  Without it, all clients share one IP bucket — the per-account key still protects individual
  accounts, but co-located legitimate users can transiently throttle each other. Enable
  trusted-proxy handling so `request.client.host` reflects the real client.
- Bearer-key lookups on the other `/api/v1/*` routes are not throttled by the app — put gateway
  limits in front of them.

## Audit log

Security-relevant actions are recorded in the `audit_logs` table (`id`, `event`, `project_id`,
`actor`, `ip`, `detail` JSONB, `created_at`) and surfaced as "Recent Activity" (latest 20) on each
project's settings page.

| Event | Actor | Detail |
|---|---|---|
| `config.pull` | `api:<key_prefix>` (11-char key prefix, never the key) | `{"key_count": N}` |
| `secret.set` | `user:<email>` | `{"provider": "<name>"}` |
| `secret.delete` | `user:<email>` | `{"provider": "<name>"}` |

The `config.pull` actor prefix is the key that actually authenticated the request — the bearer
resolver records the resolved key on the request, so attribution is exact even when a project uses
several ingest keys concurrently.

By contract, `detail` never contains secret values — only counts and provider names. Audit writes
are best-effort: a failed audit insert is logged (with at most the exception class name, never the
message) and never blocks or rolls back the operation being audited.

## Key rotation

- **Rotating `TOKENSURF_SECRET_KEY`** invalidates all existing ciphertext: Fernet tokens written
  under the old key cannot be decrypted with the new one, so `GET /api/v1/config` and channel
  notifications will fail until you re-enter every judge key and channel secret. Re-adding a
  secret for an existing provider upserts in place ("rotate by re-adding"); there is no bulk
  re-encryption tool.
- **Rotating `TOKENSURF_SESSION_SECRET`** invalidates every session cookie (all users are logged
  out) and every outstanding CSRF token, since both are signed with it. It does not affect ingest
  keys or encrypted secrets.
- **Rotating an ingest key**: mint a replacement with `tokensurf-server create-key <project-slug>`
  and update your CI. There is no revoke command; to revoke a key, delete its row from the
  `project_api_keys` table.

## Known limitations and deployment checklist

The app deliberately leaves several controls to the deployment layer. Before exposing a server
beyond localhost:

- **TLS**: terminate HTTPS at your reverse proxy and serve the dashboard only over it. Set
  `TOKENSURF_SECURE_COOKIES=true` so the session and CSRF cookies carry the `Secure` flag. The app
  emits no HSTS/CSP/X-Frame-Options headers — add those at the proxy.
- **Request size**: there is no app-level body-size cap on `POST /api/v1/runs` (intentionally
  deferred to the proxy). Set e.g. `client_max_body_size` in nginx.
- **Gateway rate limits**: cover `POST /login` and all `/api/v1/*` routes, and compensate for the
  per-process config limiter in multi-worker setups.
- **Notification egress (SSRF surface)**: notification channels POST to an admin-configured URL
  (Slack / webhook), and the test-send and gate-failure paths make the server issue that request.
  Only trusted admins can create channels (there is no self-registration). By default the server
  refuses IP-literal targets in the link-local / cloud-metadata range (169.254.0.0/16, fe80::/10) in
  any encoding, but it does NOT resolve hostnames — a hostname pointing at an internal address is
  allowed. Set `TOKENSURF_BLOCK_PRIVATE_WEBHOOKS=true` to resolve every target and also refuse
  loopback/private/reserved addresses. Because `httpx` re-resolves on connect, DNS rebinding is only
  fully mitigated by running the server on an egress-restricted network (or a forward proxy allow-list).
- **Client IP in the audit log**: `config.pull` records `request.client.host`. Behind a reverse
  proxy every pull is attributed to the proxy's IP unless you enable trusted-proxy handling
  (uvicorn `--proxy-headers` with `--forwarded-allow-ips`, or an equivalent). Do not trust
  `X-Forwarded-For` without a trusted-proxy allow-list.
- **Database backups**: Postgres holds the run data, audit log, and secret ciphertext. Back up the
  database *and* store `TOKENSURF_SECRET_KEY` separately (a secret manager, not the same backup) —
  ciphertext without the key is unrecoverable, and the key without access controls decrypts
  everything.
- **Credential scope**: an ingest key is project-scoped but is more than a push token — it can
  push runs, fetch that project's individual runs by id (there is no list endpoint), and **pull
  the project's decrypted judge keys** via `/api/v1/config`. Treat ingest keys with the same care
  as the provider keys behind them.
- **Exposed unauthenticated paths**: `/healthz`, `/static`, the Swagger UI at `/api/docs`, and the
  OpenAPI schema at `/openapi.json` need no auth. Restrict them at the proxy if your threat model
  requires it.
- **`.env` hygiene**: the server reads secrets from the environment or a `.env` file; keep that
  file out of images and version control and readable only by the service user.

## Responsible disclosure

If you find a vulnerability, please report it privately — use GitHub's "Report a vulnerability"
(private security advisory) on the repository or contact the maintainers directly, rather than
opening a public issue. Include reproduction steps and give us a reasonable window to ship a fix
before public disclosure.
