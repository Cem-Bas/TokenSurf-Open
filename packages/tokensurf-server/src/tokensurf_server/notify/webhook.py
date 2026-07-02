"""Generic webhook notifier."""

from __future__ import annotations

import httpx

from tokensurf_server.crypto import decrypt


def _post(url: str, json: dict) -> None:
    """Isolated httpx POST — monkeypatched in tests."""
    httpx.post(url, json=json, timeout=5).raise_for_status()


class WebhookNotifier:
    def send(self, *, run, failed_gates, channel) -> None:
        url = decrypt(channel.secret_enc)
        _post(
            url,
            {
                "project": run.project_id,
                "run_id": run.id,
                "label": run.label,
                "pass_rate": run.pass_rate,
                "failed_gates": [g.name for g in failed_gates],
            },
        )
