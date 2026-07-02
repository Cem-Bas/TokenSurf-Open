"""Notification package — Notifier protocol, dispatcher, per-channel implementations."""

from __future__ import annotations

import logging
from typing import Protocol

from tokensurf.core.ids import new_id

from tokensurf_server.models import NotificationLog

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, *, run, failed_gates, channel) -> None: ...


def build_message(run, failed_gates) -> str:
    """Human-readable summary: run id, label, pass_rate, failing gate names."""
    parts = [f"TokenSurf | run {run.id}"]
    if run.label:
        parts.append(f"label={run.label}")
    parts.append(f"pass_rate={run.pass_rate:.2f}")
    if failed_gates:
        gate_names = ", ".join(g.name for g in failed_gates)
        parts.append(f"Failed gates: {gate_names}")
    return " | ".join(parts)


def get_notifier(type_: str) -> Notifier:
    """Return a Notifier for the given channel type; raises ValueError on unknown type."""
    if type_ == "slack":
        from tokensurf_server.notify.slack import SlackNotifier

        return SlackNotifier()
    if type_ == "webhook":
        from tokensurf_server.notify.webhook import WebhookNotifier

        return WebhookNotifier()
    if type_ == "email":
        from tokensurf_server.notify.email import EmailNotifier

        return EmailNotifier()
    raise ValueError(f"Unknown notifier type: {type_!r}")


def send_for_run(session, channels, run, failed_gates) -> None:
    """Fire each channel; swallow per-channel failures; write a NotificationLog row per attempt."""
    for channel in channels:
        try:
            get_notifier(channel.type).send(run=run, failed_gates=failed_gates, channel=channel)
            session.add(
                NotificationLog(
                    id=new_id(),
                    channel_id=channel.id,
                    run_id=run.id,
                    ok=True,
                    error=None,
                )
            )
            logger.info("Notification ok channel=%s run=%s", channel.id, run.id)
        except Exception as exc:
            # SECURITY (spec §10): the channel secret IS the webhook/Slack URL, and
            # httpx's HTTPStatusError message embeds the full URL. NEVER persist or log
            # str(exc) here — store only the exception class name so the decrypted secret
            # cannot leak into notification_logs.error or the application log.
            err = type(exc).__name__
            logger.warning(
                "Notification failed channel=%s run=%s error=%s", channel.id, run.id, err
            )
            session.add(
                NotificationLog(
                    id=new_id(),
                    channel_id=channel.id,
                    run_id=run.id,
                    ok=False,
                    error=err,
                )
            )
        session.commit()
