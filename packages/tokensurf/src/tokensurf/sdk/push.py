"""HTTP push client — sends an EvalReport to a TokenSurf Server instance.

Requires the optional 'push' extra:
    pip install "tokensurf[push]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from tokensurf.core.models import EvalReport

if TYPE_CHECKING:
    import httpx  # type-only — NOT imported at runtime so the core CLI stays httpx-free


class RunRef(BaseModel):
    """Minimal reference returned after a successful ingest."""

    run_id: str
    project: str
    pass_rate: float
    n_cases: int


class PushError(Exception):
    """Raised when the server rejects or fails to process the push.

    Never swallowed — a push failure must surface immediately so CI steps fail loudly.
    """


def _make_client(timeout: float) -> httpx.Client:
    """Create an httpx.Client; isolated as a function so tests can monkeypatch it.

    httpx is imported lazily here (only when an actual push happens) so that
    importing `tokensurf.sdk.push` — and therefore running the core `tokensurf`
    CLI — never pulls in httpx. httpx lives only in the optional `push` extra.
    """
    import httpx

    return httpx.Client(timeout=timeout)


def push_report(
    report: EvalReport,
    *,
    server_url: str,
    api_key: str,
    label: str | None = None,
    metadata: dict | None = None,
    timeout: float = 30.0,
) -> RunRef:
    """POST *report* to ``{server_url}/api/v1/runs`` with bearer auth.

    Args:
        report: The EvalReport produced by the eval harness.
        server_url: Base URL of the TokenSurf Server instance (no trailing slash).
        api_key: Project ingest key (``tsk_...``).
        label: Optional human-readable label for this run (branch name, git sha, etc.).
        metadata: Optional free-form dict stored as ``source_metadata`` on the run.
        timeout: HTTP timeout in seconds (default 30).

    Returns:
        RunRef with the server-assigned run_id and summary stats.

    Raises:
        PushError: On any non-2xx response. Includes status code and a body snippet.
    """
    payload = {
        "label": label,
        "report": report.model_dump(mode="json"),
        "metadata": metadata,
    }
    with _make_client(timeout) as client:
        response = client.post(
            f"{server_url}/api/v1/runs",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    if not response.is_success:
        snippet = response.text[:200]
        raise PushError(f"push failed: HTTP {response.status_code} — {snippet}")
    return RunRef.model_validate(response.json())
