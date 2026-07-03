"""Runtime configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SESSION_SECRET_DEFAULT = "tokensurf-dev-secret-change-me"
MIN_SESSION_SECRET_LEN = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str  # env DATABASE_URL — required; missing raises ValidationError at startup
    host: str = "0.0.0.0"  # env HOST
    port: int = 8000  # env PORT
    session_secret: str = Field(
        default=INSECURE_SESSION_SECRET_DEFAULT,
        validation_alias="TOKENSURF_SESSION_SECRET",
    )  # env TOKENSURF_SESSION_SECRET

    # Encryption key for channel secrets (env TOKENSURF_SECRET_KEY)
    secret_key: str | None = Field(default=None, validation_alias="TOKENSURF_SECRET_KEY")

    # Config-pull rate limit for GET /api/v1/config (env TOKENSURF_CONFIG_RATE_LIMIT)
    config_rate_limit: str = Field(
        default="30/60",
        validation_alias="TOKENSURF_CONFIG_RATE_LIMIT",
    )

    # Set the Secure flag on session + CSRF cookies (requires HTTPS). Default False so
    # local HTTP development works; set to true in any TLS-terminated deployment.
    secure_cookies: bool = Field(default=False, validation_alias="TOKENSURF_SECURE_COOKIES")

    # Per-client rate limit for POST /login as "count/window_seconds" (brute-force throttle).
    login_rate_limit: str = Field(default="10/60", validation_alias="TOKENSURF_LOGIN_RATE_LIMIT")

    # Path to the file holding the first-run admin setup token (env
    # TOKENSURF_SETUP_TOKEN_PATH). Read by GET/POST /setup while no users exist yet.
    setup_token_path: str = Field(
        default="./tokensurf_setup_token", validation_alias="TOKENSURF_SETUP_TOKEN_PATH"
    )

    # When true, notification webhooks may not target private/loopback/reserved addresses.
    # Link-local (cloud-metadata) targets are always refused regardless of this flag.
    webhook_block_private: bool = Field(
        default=False, validation_alias="TOKENSURF_BLOCK_PRIVATE_WEBHOOKS"
    )

    # SMTP settings for email notifications (all optional)
    smtp_host: str | None = Field(default=None, validation_alias="TOKENSURF_SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="TOKENSURF_SMTP_PORT")
    smtp_user: str | None = Field(default=None, validation_alias="TOKENSURF_SMTP_USER")
    smtp_password: str | None = Field(default=None, validation_alias="TOKENSURF_SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, validation_alias="TOKENSURF_SMTP_FROM")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
