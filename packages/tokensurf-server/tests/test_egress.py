"""Tests for the notification-egress SSRF guard (notify/egress.py)."""

from __future__ import annotations

import pytest

from tokensurf_server.notify.egress import WebhookURLBlocked, check_webhook_url


def test_link_local_metadata_always_blocked():
    # 169.254.169.254 (cloud metadata) is refused even with block_private off.
    with pytest.raises(WebhookURLBlocked):
        check_webhook_url("http://169.254.169.254/latest/meta-data/")


def test_public_literal_ip_allowed_by_default():
    check_webhook_url("https://93.184.216.34/hook")  # no raise


def test_private_ip_allowed_by_default_but_blocked_when_strict():
    check_webhook_url("http://10.0.0.5/hook")  # self-hosters may target internal hosts
    with pytest.raises(WebhookURLBlocked):
        check_webhook_url("http://10.0.0.5/hook", block_private=True)


def test_loopback_blocked_only_when_strict():
    check_webhook_url("http://127.0.0.1:9000/hook")
    with pytest.raises(WebhookURLBlocked):
        check_webhook_url("http://127.0.0.1:9000/hook", block_private=True)


def test_non_http_scheme_blocked():
    for bad in ("ftp://example.com/x", "file:///etc/passwd", "gopher://x/1"):
        with pytest.raises(WebhookURLBlocked):
            check_webhook_url(bad)


def test_hostname_not_resolved_by_default():
    # A hostname that would never resolve must still pass when block_private is off
    # (proves no DNS lookup happens on the default path).
    check_webhook_url("https://nonexistent.invalid.example/services/abc")
