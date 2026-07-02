"""Slack webhook notifier."""

from __future__ import annotations

import httpx

from tokensurf_server.config import get_settings
from tokensurf_server.crypto import decrypt
from tokensurf_server.notify import build_message
from tokensurf_server.notify.egress import check_webhook_url


def _post(url: str, json: dict) -> None:
    """Isolated httpx POST — monkeypatched in tests."""
    httpx.post(url, json=json, timeout=5).raise_for_status()


class SlackNotifier:
    def send(self, *, run, failed_gates, channel) -> None:
        url = decrypt(channel.secret_enc)
        check_webhook_url(url, block_private=get_settings().webhook_block_private)
        _post(url, {"text": build_message(run, failed_gates)})
