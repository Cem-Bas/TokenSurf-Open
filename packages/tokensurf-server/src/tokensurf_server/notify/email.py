"""SMTP email notifier."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from tokensurf_server.config import get_settings
from tokensurf_server.notify import build_message


def _send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str | None,
    smtp_password: str | None,
    smtp_from: str | None,
    to: str,
    subject: str,
    body: str,
) -> None:
    """Isolated SMTP send — monkeypatched in tests."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from or smtp_user or "tokensurf@localhost"
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)


class EmailNotifier:
    def send(self, *, run, failed_gates, channel) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            raise RuntimeError("TOKENSURF_SMTP_HOST is required to send email notifications")
        to: str | None = (channel.config or {}).get("to")
        if not to:
            raise RuntimeError("Email channel config is missing a 'to' address")
        body = build_message(run, failed_gates)
        _send_email(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            smtp_from=settings.smtp_from,
            to=to,
            subject=f"TokenSurf alert: run {run.id}",
            body=body,
        )
