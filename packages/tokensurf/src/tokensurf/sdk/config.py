"""Config-pull client — fetches judge keys from a TokenSurf Server instance.

Requires the optional 'push' extra (httpx):
    pip install "tokensurf[push]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx  # type-only — NOT imported at runtime so the core CLI stays httpx-free


class ConfigError(Exception):
    """Raised when the server returns a non-2xx response during config pull.

    Never swallowed — a config pull failure must surface immediately so CI steps fail loudly.
    """


def _make_client(timeout: float) -> httpx.Client:
    """Create an httpx.Client; isolated so tests can monkeypatch it.

    httpx is imported lazily here so that importing tokensurf.sdk.config never
    pulls in httpx outside of the optional 'push' extra.
    """
    import httpx

    return httpx.Client(timeout=timeout)


def fetch_config(*, server_url: str, api_key: str, timeout: float = 30.0) -> dict:
    """GET {server_url}/api/v1/config with bearer auth; return the parsed response dict.

    Args:
        server_url: Base URL of the TokenSurf Server instance (no trailing slash).
        api_key: Project ingest key (``tsk_...``).
        timeout: HTTP timeout in seconds (default 30).

    Returns:
        Parsed JSON dict, e.g. ``{"judge_keys": {"openai": "sk-...", ...}}``.

    Raises:
        ConfigError: On any non-2xx response. Includes status code in the message.
    """
    with _make_client(timeout) as client:
        response = client.get(
            f"{server_url}/api/v1/config",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if not response.is_success:
        snippet = response.text[:200]
        raise ConfigError(f"config pull failed: HTTP {response.status_code} — {snippet}")
    return response.json()
