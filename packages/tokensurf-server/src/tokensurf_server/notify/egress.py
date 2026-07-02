"""SSRF guard for notification egress.

Notification channels POST to an admin-configured URL (Slack / webhook). Only trusted
admins can create channels, but a careless or malicious admin could point one at an
internal service or a cloud metadata endpoint. This module refuses the most dangerous
targets before the server ever makes the request.

Policy:
- IP-LITERAL targets are always checked, in any common encoding: canonical dotted
  (``169.254.169.254``), bare integer (``2852039166``), dotted hex/octal
  (``0xA9.0xFE.0xA9.0xFE``), a trailing dot, and IPv4-mapped IPv6 (``::ffff:169.254.169.254``)
  are all normalized to the underlying address. Link-local addresses (169.254.0.0/16,
  fe80::/10 — the cloud-metadata range) are refused for such literals regardless of
  ``block_private``; loopback / private / reserved / multicast are refused only when
  ``block_private`` is set.
- HOSTNAME targets are resolved and checked (all resolved addresses) ONLY when
  ``block_private`` is set (env ``TOKENSURF_BLOCK_PRIVATE_WEBHOOKS``). By default a
  hostname is allowed without a DNS lookup — so a hostname that resolves to an internal
  address is NOT caught in the default configuration. Operators who need that protection
  should set ``TOKENSURF_BLOCK_PRIVATE_WEBHOOKS=true`` and/or run the server on an
  egress-restricted network. Note: even with resolution, ``httpx`` re-resolves the host
  when it connects, so DNS rebinding is only fully mitigated by a network egress control.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class WebhookURLBlocked(ValueError):
    """Raised when a notification target URL is refused by the egress policy."""


def _unwrap(ip: IPAddress) -> IPAddress:
    """Unwrap an IPv4-mapped IPv6 address to the underlying IPv4 address."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _literal_ip(host: str) -> IPAddress | None:
    """Return the address a literal host encodes (any common form), or None for a hostname."""
    h = host.rstrip(".")
    for parse in (
        lambda: ipaddress.ip_address(h),  # canonical IPv4 / IPv6 literal
        # inet_aton decodes dotted/hex/octal/short AND bare-integer forms with the SAME C
        # semantics the OS resolver uses — critically, it reads a leading-zero integer as
        # octal (as getaddrinfo does). A hand-rolled int(h) would read it as decimal and
        # create a parser differential the resolver would then defeat.
        lambda: ipaddress.ip_address(socket.inet_aton(h)),
    ):
        try:
            ip = parse()
        except (ValueError, OverflowError, OSError):
            ip = None
        if ip is not None:
            return _unwrap(ip)
    return None


def _classify_blocked(ip: IPAddress, *, block_private: bool) -> str | None:
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

    ip = _literal_ip(host)
    if ip is not None:
        reason = _classify_blocked(ip, block_private=block_private)
        if reason:
            raise WebhookURLBlocked(f"refused webhook target ({reason})")
        return

    # Real hostname: only resolve + check in strict mode (keeps the default path DNS-free).
    if not block_private:
        return
    try:
        infos = socket.getaddrinfo(host, parsed.port or None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WebhookURLBlocked(f"could not resolve webhook host {host!r}") from exc
    for info in infos:
        resolved = _unwrap(ipaddress.ip_address(info[4][0]))
        reason = _classify_blocked(resolved, block_private=block_private)
        if reason:
            raise WebhookURLBlocked(f"refused webhook target {host!r} -> {resolved} ({reason})")
