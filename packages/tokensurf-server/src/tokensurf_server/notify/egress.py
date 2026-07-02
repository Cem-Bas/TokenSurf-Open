"""SSRF guard for notification egress.

Notification channels POST to an admin-configured URL (Slack / webhook). Only trusted
admins can create channels, but a careless or malicious admin could point one at an
internal service or a cloud metadata endpoint. This module refuses the most dangerous
targets before the server ever makes the request.

Policy:
- Link-local addresses (169.254.0.0/16, fe80::/10 — the cloud-metadata range) are ALWAYS
  refused. They are never a legitimate webhook target.
- Loopback / private / reserved / multicast / unspecified addresses are refused only when
  ``block_private`` is set (env ``TOKENSURF_BLOCK_PRIVATE_WEBHOOKS``), because self-hosters
  legitimately POST to internal endpoints on their own network.
- A literal-IP host is checked directly (no DNS). A hostname is resolved and every
  resolved address is checked only when ``block_private`` is set; otherwise a hostname is
  allowed without a DNS lookup, preserving current behavior by default.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class WebhookURLBlocked(ValueError):
    """Raised when a notification target URL is refused by the egress policy."""


def _classify_blocked(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, block_private: bool
) -> str | None:
    """Return a reason string if the address is blocked, else None."""
    if ip.is_link_local:
        return "link-local / cloud-metadata address"
    if block_private and (
        ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    ):
        return "private / loopback / reserved address"
    return None


def check_webhook_url(url: str, *, block_private: bool = False) -> None:
    """Raise WebhookURLBlocked if ``url`` is not an allowed notification target."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebhookURLBlocked(f"unsupported URL scheme {parsed.scheme!r} (need http/https)")
    host = parsed.hostname
    if not host:
        raise WebhookURLBlocked("URL has no host")

    # Literal IP host: check directly, no DNS.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        reason = _classify_blocked(ip, block_private=block_private)
        if reason:
            raise WebhookURLBlocked(f"refused webhook target ({reason})")
        return

    # Hostname: only resolve + check when strict mode is on (avoids DNS by default).
    if not block_private:
        return
    try:
        infos = socket.getaddrinfo(host, parsed.port or None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WebhookURLBlocked(f"could not resolve webhook host {host!r}") from exc
    for info in infos:
        addr = info[4][0]
        resolved = ipaddress.ip_address(addr)
        reason = _classify_blocked(resolved, block_private=block_private)
        if reason:
            raise WebhookURLBlocked(f"refused webhook target {host!r} -> {addr} ({reason})")
