from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id
from typer.testing import CliRunner

_TEST_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://tokensurf:changeme@localhost:5432/tokensurf",
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _patch_db_url(monkeypatch):
    """Ensure the CLI uses the test DB, the settings cache sees it, and crypto is available."""
    monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
    monkeypatch.setenv("TOKENSURF_SECRET_KEY", "test-secret-key")
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def test_engine():
    """Engine pointing at the test DB with all tables created."""
    from sqlalchemy import create_engine

    from tokensurf_server.db import Base

    engine = create_engine(_TEST_DB_URL)
    try:
        import tokensurf_server.models  # noqa: F401 — register new tables on metadata
    except ModuleNotFoundError:
        pass
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db_rows(test_engine):
    """Record row IDs before each test; delete any new rows in teardown.

    This fixture pays down the test-isolation debt: admin-CLI commands commit
    real rows into the shared dev DB. By taking a before/after snapshot and
    deleting the delta, a full suite run leaves row counts unchanged.
    """
    from tokensurf_server.models import Project, User

    with Session(test_engine) as s:
        pre_project_ids = set(s.execute(select(Project.id)).scalars())
        pre_user_ids = set(s.execute(select(User.id)).scalars())

    yield

    with Session(test_engine) as s:
        new_project_ids = set(s.execute(select(Project.id)).scalars()) - pre_project_ids
        new_user_ids = set(s.execute(select(User.id)).scalars()) - pre_user_ids

        for pid in new_project_ids:
            # Delete child rows in FK-safe order before removing the project.
            sub = "SELECT id FROM runs WHERE project_id=:p"
            for stmt in [
                f"DELETE FROM notification_logs WHERE run_id IN ({sub})",
                f"DELETE FROM run_gate_results WHERE run_id IN ({sub})",
                f"DELETE FROM scores WHERE run_id IN ({sub})",
                f"DELETE FROM case_results WHERE run_id IN ({sub})",
                "DELETE FROM runs WHERE project_id=:p",
                "DELETE FROM notification_channels WHERE project_id=:p",
                "DELETE FROM quality_gates WHERE project_id=:p",
                "DELETE FROM project_api_keys WHERE project_id=:p",
                "DELETE FROM audit_logs WHERE project_id=:p",
                "DELETE FROM project_secrets WHERE project_id=:p",
                "DELETE FROM projects WHERE id=:p",
            ]:
                s.execute(text(stmt), {"p": pid})
        for uid in new_user_ids:
            s.execute(text("DELETE FROM users WHERE id=:u"), {"u": uid})
        s.commit()

    # Post-teardown assertion: DB is restored to pre-test state.
    with Session(test_engine) as s:
        from tokensurf_server.models import Project, User  # re-import in new scope

        final_project_ids = set(s.execute(select(Project.id)).scalars())
        final_user_ids = set(s.execute(select(User.id)).scalars())
    assert not (final_project_ids - pre_project_ids), (
        "_clean_db_rows: project rows remain after cleanup"
    )
    assert not (final_user_ids - pre_user_ids), "_clean_db_rows: user rows remain after cleanup"


# ── pre-existing tests (unchanged) ────────────────────────────────────────────


def test_create_project_prints_id_and_slug(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import Project

    slug = "cli-proj-" + new_id()[:8]
    result = runner.invoke(cli_app, ["create-project", "CLI Project", "--slug", slug])
    assert result.exit_code == 0, result.output
    assert f"slug={slug}" in result.output

    with Session(test_engine) as session:
        project = session.scalar(select(Project).where(Project.slug == slug))
        assert project is not None
        assert project.name == "CLI Project"


def test_create_project_auto_slug(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import Project

    unique_name = "Auto Slug Test " + new_id()[:6]
    result = runner.invoke(cli_app, ["create-project", unique_name])
    assert result.exit_code == 0, result.output
    assert "slug=" in result.output

    slug_part = result.output.split("slug=")[1].strip()
    with Session(test_engine) as session:
        project = session.scalar(select(Project).where(Project.slug == slug_part))
        assert project is not None


def test_create_key_prints_raw_tsk_key(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import ProjectApiKey
    from tokensurf_server.security import hash_key

    slug = "key-proj-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Key Project", "--slug", slug])

    result = runner.invoke(cli_app, ["create-key", slug, "--label", "ci"])
    assert result.exit_code == 0, result.output
    raw_key = result.output.strip()
    assert raw_key.startswith("tsk_")

    with Session(test_engine) as session:
        pak = session.scalar(
            select(ProjectApiKey).where(ProjectApiKey.key_hash == hash_key(raw_key))
        )
        assert pak is not None
        assert pak.key_prefix == raw_key[:11]
        assert pak.label == "ci"


def test_create_key_unknown_slug_exits_nonzero() -> None:
    from tokensurf_server.admin_cli import app as cli_app

    result = runner.invoke(cli_app, ["create-key", "does-not-exist-" + new_id()[:8]])
    assert result.exit_code != 0


def test_migrate_runs_without_error() -> None:
    """Smoke-test: alembic upgrade head should exit 0 against the test DB."""
    from tokensurf_server.admin_cli import app as cli_app

    result = runner.invoke(cli_app, ["migrate"])
    assert result.exit_code == 0, result.output


# ── new: create-gate ──────────────────────────────────────────────────────────


def test_create_gate_inserts_gate_row(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import QualityGate

    slug = "gate-proj-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Gate Project", "--slug", slug])

    result = runner.invoke(cli_app, ["create-gate", slug, "pass rate check", "pass_rate", "0.9"])
    assert result.exit_code == 0, result.output
    gate_id = result.output.strip()
    assert gate_id  # printed a non-empty id

    with Session(test_engine) as s:
        gate = s.scalar(select(QualityGate).where(QualityGate.id == gate_id))
    assert gate is not None
    assert gate.name == "pass rate check"
    assert gate.metric == "pass_rate"
    assert gate.threshold == 0.9
    assert gate.comparison == "gte"  # default
    assert gate.scorer is None
    assert gate.enabled is True


def test_create_gate_custom_comparison_and_scorer(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import QualityGate

    slug = "gate-scorer-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Gate Scorer Project", "--slug", slug])

    result = runner.invoke(
        cli_app,
        [
            "create-gate",
            slug,
            "scorer threshold",
            "scorer_pass_rate",
            "0.85",
            "--comparison",
            "gte",
            "--scorer",
            "accuracy",
        ],
    )
    assert result.exit_code == 0, result.output
    gate_id = result.output.strip()

    with Session(test_engine) as s:
        gate = s.scalar(select(QualityGate).where(QualityGate.id == gate_id))
    assert gate is not None
    assert gate.scorer == "accuracy"
    assert gate.comparison == "gte"
    assert gate.threshold == 0.85


def test_create_gate_unknown_project_exits_nonzero() -> None:
    from tokensurf_server.admin_cli import app as cli_app

    result = runner.invoke(
        cli_app,
        ["create-gate", "no-such-project-" + new_id()[:8], "name", "pass_rate", "0.9"],
    )
    assert result.exit_code != 0


# ── new: create-channel ───────────────────────────────────────────────────────


def test_create_channel_encrypts_secret_at_rest(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.crypto import decrypt
    from tokensurf_server.models import NotificationChannel

    slug = "chan-proj-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Chan Project", "--slug", slug])

    result = runner.invoke(
        cli_app,
        ["create-channel", slug, "Slack Alerts", "https://hooks.slack.com/test", "--type", "slack"],
    )
    assert result.exit_code == 0, result.output
    channel_id = result.output.strip()

    with Session(test_engine) as s:
        chan = s.scalar(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    assert chan is not None
    assert chan.name == "Slack Alerts"
    assert chan.type == "slack"
    # Secret must NOT be stored as plaintext
    assert chan.secret_enc != "https://hooks.slack.com/test"
    # But must round-trip back to the original plaintext
    assert decrypt(chan.secret_enc) == "https://hooks.slack.com/test"


def test_create_channel_email_stores_to_in_config(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import NotificationChannel

    slug = "email-proj-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Email Project", "--slug", slug])

    result = runner.invoke(
        cli_app,
        [
            "create-channel",
            slug,
            "Email Alerts",
            "smtp-password-here",
            "team@example.com",
            "--type",
            "email",
        ],
    )
    assert result.exit_code == 0, result.output
    channel_id = result.output.strip()

    with Session(test_engine) as s:
        chan = s.scalar(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    assert chan is not None
    assert chan.config == {"to": "team@example.com"}


def test_create_channel_slack_no_to_gives_none_config(test_engine) -> None:
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import NotificationChannel

    slug = "slack-cfg-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Slack Config Project", "--slug", slug])

    result = runner.invoke(
        cli_app,
        ["create-channel", slug, "Slack No-To", "https://hooks.slack.com/x", "--type", "slack"],
    )
    assert result.exit_code == 0, result.output
    channel_id = result.output.strip()

    with Session(test_engine) as s:
        chan = s.scalar(select(NotificationChannel).where(NotificationChannel.id == channel_id))
    assert chan is not None
    assert chan.config is None  # empty `to` → no config dict stored


def test_create_channel_unknown_project_exits_nonzero() -> None:
    from tokensurf_server.admin_cli import app as cli_app

    result = runner.invoke(
        cli_app,
        ["create-channel", "no-such-" + new_id()[:8], "Name", "secret", "--type", "slack"],
    )
    assert result.exit_code != 0


# ── cleanup verification ──────────────────────────────────────────────────────


def test_cleanup_fixture_leaves_no_project_residue(test_engine) -> None:
    """The _clean_db_rows autouse fixture deletes committed rows in teardown.

    This test verifies that a project created by the CLI is visible during the
    test body (the commit happened) and that the post-teardown assertion in the
    fixture itself will pass — i.e. the fixture successfully deletes it.
    """
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import Project

    with Session(test_engine) as s:
        before_count = s.scalar(select(func.count(Project.id)))

    slug = "cleanup-verify-" + new_id()[:8]
    result = runner.invoke(cli_app, ["create-project", "Cleanup Verify", "--slug", slug])
    assert result.exit_code == 0

    with Session(test_engine) as s:
        during_count = s.scalar(select(func.count(Project.id)))
    assert during_count == (before_count or 0) + 1, (
        "project must be committed and visible during test body"
    )
    # After this test function returns, _clean_db_rows teardown deletes the row
    # and asserts final_count == before_count.  If that assertion fires, this
    # test is marked as ERROR — the desired failure mode.


# ── new: create-secret ───────────────────────────────────────────────────────


def test_create_secret_stores_encrypted(test_engine):
    from tokensurf_server.admin_cli import app as cli_app
    from tokensurf_server.models import ProjectSecret

    slug = "secret-proj-" + new_id()[:8]
    runner.invoke(cli_app, ["create-project", "Secret Project", "--slug", slug])

    result = runner.invoke(cli_app, ["create-secret", slug, "openai", "sk-super-secret-value"])
    assert result.exit_code == 0, result.output
    assert "secret set for openai" in result.output
    # the plaintext key must NOT appear in the CLI output
    assert "sk-super-secret-value" not in result.output

    with Session(test_engine) as s:
        row = s.scalar(select(ProjectSecret).where(ProjectSecret.provider == "openai"))
        assert row is not None
        # stored value is ciphertext, not the plaintext
        assert row.key_enc != "sk-super-secret-value"
        assert row.key_enc.startswith("gAAAAA")  # Fernet token prefix


def test_create_secret_unknown_project_exits_nonzero():
    from tokensurf_server.admin_cli import app as cli_app

    result = runner.invoke(cli_app, ["create-secret", "no-such-" + new_id()[:8], "openai", "sk-x"])
    assert result.exit_code != 0
