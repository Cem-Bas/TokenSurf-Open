"""Tests for the tokensurf_server.notify package."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tokensurf.core.ids import new_id

from tokensurf_server.config import get_settings
from tokensurf_server.crypto import encrypt
from tokensurf_server.models import NotificationChannel, NotificationLog, Project, Run
from tokensurf_server.notify import build_message, send_for_run


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch):
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "test-secret-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------


def test_build_message_contains_label() -> None:
    run = SimpleNamespace(id="r1", label="nightly", pass_rate=0.9, project_id="p1")
    msg = build_message(run, [])
    assert "nightly" in msg


def test_build_message_contains_failed_gate_name() -> None:
    run = SimpleNamespace(id="r1", label="ci", pass_rate=0.8, project_id="p1")
    gate = SimpleNamespace(name="p50-latency")
    msg = build_message(run, [gate])
    assert "p50-latency" in msg


def test_build_message_contains_pass_rate() -> None:
    run = SimpleNamespace(id="r1", label=None, pass_rate=0.75, project_id="p1")
    msg = build_message(run, [])
    assert "0.75" in msg


# ---------------------------------------------------------------------------
# SlackNotifier — monkeypatch _post to capture (url, json)
# ---------------------------------------------------------------------------


def test_slack_notifier_posts_to_decrypted_url(monkeypatch) -> None:
    import tokensurf_server.notify.slack as slack_mod

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(slack_mod, "_post", lambda url, json: captured.append((url, json)))

    plaintext_url = "https://hooks.slack.com/services/T000/B000/xxxxxxxxxxx"
    channel = SimpleNamespace(
        id=new_id(), type="slack", secret_enc=encrypt(plaintext_url), config=None
    )
    run = SimpleNamespace(id="r1", label="gate-test", pass_rate=0.5, project_id="p1")
    gate = SimpleNamespace(name="accuracy-gate")

    from tokensurf_server.notify.slack import SlackNotifier

    SlackNotifier().send(run=run, failed_gates=[gate], channel=channel)

    assert len(captured) == 1
    url, payload = captured[0]
    assert url == plaintext_url
    # Must NOT post the raw ciphertext as the URL
    assert url != channel.secret_enc
    assert "gate-test" in payload["text"]
    assert "accuracy-gate" in payload["text"]


def test_slack_notifier_payload_has_text_key(monkeypatch) -> None:
    import tokensurf_server.notify.slack as slack_mod

    captured: list[dict] = []
    monkeypatch.setattr(slack_mod, "_post", lambda url, json: captured.append(json))

    channel = SimpleNamespace(
        id=new_id(),
        type="slack",
        secret_enc=encrypt("https://hooks.slack.com/test"),
        config=None,
    )
    run = SimpleNamespace(id="r2", label="r", pass_rate=1.0, project_id="p1")

    from tokensurf_server.notify.slack import SlackNotifier

    SlackNotifier().send(run=run, failed_gates=[], channel=channel)

    assert "text" in captured[0]


# ---------------------------------------------------------------------------
# WebhookNotifier — monkeypatch _post to capture (url, json)
# ---------------------------------------------------------------------------


def test_webhook_notifier_posts_to_decrypted_url(monkeypatch) -> None:
    import tokensurf_server.notify.webhook as webhook_mod

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(webhook_mod, "_post", lambda url, json: captured.append((url, json)))

    plaintext_url = "https://myapp.example.com/webhooks/tokensurf"
    channel = SimpleNamespace(
        id=new_id(), type="webhook", secret_enc=encrypt(plaintext_url), config=None
    )
    gate = SimpleNamespace(name="latency-gate")
    run = SimpleNamespace(id="run-abc", label="nightly", pass_rate=0.6, project_id="proj-1")

    from tokensurf_server.notify.webhook import WebhookNotifier

    WebhookNotifier().send(run=run, failed_gates=[gate], channel=channel)

    assert len(captured) == 1
    url, payload = captured[0]
    assert url == plaintext_url
    assert url != channel.secret_enc
    assert payload["run_id"] == "run-abc"
    assert payload["label"] == "nightly"
    assert payload["pass_rate"] == pytest.approx(0.6)
    assert "latency-gate" in payload["failed_gates"]


def test_webhook_notifier_payload_shape(monkeypatch) -> None:
    import tokensurf_server.notify.webhook as webhook_mod

    captured: list[dict] = []
    monkeypatch.setattr(webhook_mod, "_post", lambda url, json: captured.append(json))

    channel = SimpleNamespace(
        id=new_id(),
        type="webhook",
        secret_enc=encrypt("https://example.com/hook"),
        config=None,
    )
    run = SimpleNamespace(id="run-xyz", label=None, pass_rate=1.0, project_id="proj-2")

    from tokensurf_server.notify.webhook import WebhookNotifier

    WebhookNotifier().send(run=run, failed_gates=[], channel=channel)

    payload = captured[0]
    for key in ("project", "run_id", "label", "pass_rate", "failed_gates"):
        assert key in payload, f"key {key!r} missing from webhook payload"
    assert payload["failed_gates"] == []


# ---------------------------------------------------------------------------
# EmailNotifier — monkeypatch _send_email to capture args
# ---------------------------------------------------------------------------


def test_email_notifier_calls_send_email_with_to_and_body(monkeypatch) -> None:
    import tokensurf_server.notify.email as email_mod

    monkeypatch.setenv("TOKENSURF_SMTP_HOST", "smtp.example.com")
    get_settings.cache_clear()

    sent: list[dict] = []

    def _fake_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, to, subject, body):
        sent.append({"smtp_host": smtp_host, "to": to, "subject": subject, "body": body})

    monkeypatch.setattr(email_mod, "_send_email", _fake_send)

    channel = SimpleNamespace(
        id=new_id(),
        type="email",
        secret_enc=encrypt("not-used-for-smtp"),
        config={"to": "alerts@example.com"},
    )
    run = SimpleNamespace(id="r3", label="email-run", pass_rate=0.4, project_id="p3")
    gate = SimpleNamespace(name="quality-gate")

    from tokensurf_server.notify.email import EmailNotifier

    EmailNotifier().send(run=run, failed_gates=[gate], channel=channel)

    assert len(sent) == 1
    assert sent[0]["to"] == "alerts@example.com"
    assert sent[0]["smtp_host"] == "smtp.example.com"
    body = sent[0]["body"]
    assert "email-run" in body or "quality-gate" in body


def test_email_notifier_raises_if_smtp_host_missing(monkeypatch) -> None:
    monkeypatch.delenv("TOKENSURF_SMTP_HOST", raising=False)
    get_settings.cache_clear()

    channel = SimpleNamespace(
        id=new_id(),
        type="email",
        secret_enc=encrypt("x"),
        config={"to": "a@b.com"},
    )
    run = SimpleNamespace(id="r4", label=None, pass_rate=0.0, project_id="p4")

    from tokensurf_server.notify.email import EmailNotifier

    with pytest.raises(RuntimeError, match="TOKENSURF_SMTP_HOST"):
        EmailNotifier().send(run=run, failed_gates=[], channel=channel)


# ---------------------------------------------------------------------------
# send_for_run — one channel fails; the next still fires; both get a NotificationLog
# ---------------------------------------------------------------------------


def test_send_for_run_failure_logs_ok_false_and_continues(db_session, monkeypatch) -> None:
    from sqlalchemy import select

    import tokensurf_server.notify.slack as slack_mod

    project = Project(id=new_id(), name="Notify Project", slug=f"notify-proj-{new_id()[:6]}")
    db_session.add(project)
    db_session.flush()

    run = Run(
        id=new_id(),
        project_id=project.id,
        label="multi-chan",
        status="completed",
        n_cases=1,
        pass_rate=0.5,
        mean_score=None,
        error_count=0,
        source_metadata=None,
    )
    db_session.add(run)
    db_session.flush()

    plaintext_fail = "https://hooks.slack.com/fail"
    plaintext_ok = "https://hooks.slack.com/ok"

    ch_fail = NotificationChannel(
        id=new_id(),
        project_id=project.id,
        type="slack",
        name="chan-fail",
        secret_enc=encrypt(plaintext_fail),
        enabled=True,
    )
    ch_ok = NotificationChannel(
        id=new_id(),
        project_id=project.id,
        type="slack",
        name="chan-ok",
        secret_enc=encrypt(plaintext_ok),
        enabled=True,
    )
    db_session.add(ch_fail)
    db_session.add(ch_ok)
    db_session.flush()

    ok_calls: list[str] = []

    def _fake_post(url: str, json: dict) -> None:
        if "fail" in url:
            raise RuntimeError("Slack unreachable")
        ok_calls.append(url)

    monkeypatch.setattr(slack_mod, "_post", _fake_post)

    send_for_run(db_session, [ch_fail, ch_ok], run, [])

    assert ok_calls == [plaintext_ok]

    logs = list(db_session.scalars(select(NotificationLog).where(NotificationLog.run_id == run.id)))
    assert len(logs) == 2
    fail_log = next(lg for lg in logs if not lg.ok)
    ok_log = next(lg for lg in logs if lg.ok)
    assert fail_log.error is not None
    assert ok_log.error is None


# ---------------------------------------------------------------------------
# Secret-leak guard: HTTPStatusError message must NOT appear in NotificationLog.error
# ---------------------------------------------------------------------------


def test_send_for_run_http_error_does_not_leak_secret_url(db_session, monkeypatch) -> None:
    """NotificationLog.error must be the exc class name only, never the URL."""
    import httpx
    from sqlalchemy import select

    import tokensurf_server.notify.slack as slack_mod

    project = Project(id=new_id(), name="Leak Guard Project", slug=f"leak-{new_id()[:6]}")
    db_session.add(project)
    db_session.flush()

    run = Run(
        id=new_id(),
        project_id=project.id,
        label="secret-leak-test",
        status="completed",
        n_cases=1,
        pass_rate=1.0,
        mean_score=None,
        error_count=0,
        source_metadata=None,
    )
    db_session.add(run)
    db_session.flush()

    secret_url = "https://hooks.slack.com/services/SECRET"

    ch = NotificationChannel(
        id=new_id(),
        project_id=project.id,
        type="slack",
        name="chan-secret",
        secret_enc=encrypt(secret_url),
        enabled=True,
    )
    db_session.add(ch)
    db_session.flush()

    def _fake_post(url: str, json: dict) -> None:
        # Simulate httpx raising HTTPStatusError whose message contains the decrypted URL
        request = httpx.Request("POST", url)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            f"Server error '500 Internal Server Error' for url '{url}'",
            request=request,
            response=response,
        )

    monkeypatch.setattr(slack_mod, "_post", _fake_post)

    send_for_run(db_session, [ch], run, [])

    logs = list(db_session.scalars(select(NotificationLog).where(NotificationLog.run_id == run.id)))
    assert len(logs) == 1
    log = logs[0]
    assert not log.ok
    assert log.error == "HTTPStatusError"
    assert "SECRET" not in (log.error or "")
    assert "hooks.slack.com" not in (log.error or "")
