"""DB tests for secrets_service (slice 2d A3).

Requires DATABASE_URL and TOKENSURF_SECRET_KEY in the environment.
The autouse _settings_cache fixture clears the lru_cache so monkeypatch env changes
take effect immediately (mirrors test_crypto.py pattern from 2c).
"""

from __future__ import annotations

import pytest
from tokensurf.core.ids import new_id

from tokensurf_server.crypto import SecretKeyMissing
from tokensurf_server.models import Project
from tokensurf_server.secrets_service import (
    delete_secret,
    get_decrypted_secrets,
    list_providers,
    set_secret,
)


@pytest.fixture(autouse=True)
def _settings_cache():
    """Clear lru_cache before and after every test so env changes take effect."""
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _project(db_session) -> Project:
    p = Project(id=new_id(), name="Secrets SVC Test", slug="svc-" + new_id()[:8])
    db_session.add(p)
    db_session.flush()
    return p


def test_set_list_get_decrypted_round_trip(db_session):
    p = _project(db_session)
    row = set_secret(db_session, project_id=p.id, provider="openai", plaintext="sk-test-openai")
    assert row.key_enc != "sk-test-openai"  # must be stored encrypted, not as plaintext
    providers = list_providers(db_session, p.id)
    assert providers == ["openai"]
    secrets = get_decrypted_secrets(db_session, p.id)
    assert secrets == {"openai": "sk-test-openai"}


def test_set_multiple_providers_sorted(db_session):
    p = _project(db_session)
    set_secret(db_session, project_id=p.id, provider="openai", plaintext="sk-openai")
    set_secret(db_session, project_id=p.id, provider="anthropic", plaintext="sk-anthropic")
    providers = list_providers(db_session, p.id)
    assert providers == ["anthropic", "openai"]  # sorted alphabetically
    secrets = get_decrypted_secrets(db_session, p.id)
    assert secrets == {"openai": "sk-openai", "anthropic": "sk-anthropic"}


def test_upsert_replaces_existing_secret_no_duplicate_row(db_session):
    p = _project(db_session)
    r1 = set_secret(db_session, project_id=p.id, provider="openai", plaintext="old-key")
    r2 = set_secret(db_session, project_id=p.id, provider="openai", plaintext="new-key")
    assert r1.id == r2.id  # same row was updated, not a second row inserted
    providers = list_providers(db_session, p.id)
    assert providers == ["openai"]  # still exactly one row
    secrets = get_decrypted_secrets(db_session, p.id)
    assert secrets["openai"] == "new-key"


def test_delete_removes_secret_and_returns_true(db_session):
    p = _project(db_session)
    set_secret(db_session, project_id=p.id, provider="gemini", plaintext="gem-key")
    deleted = delete_secret(db_session, project_id=p.id, provider="gemini")
    assert deleted is True
    assert list_providers(db_session, p.id) == []


def test_delete_nonexistent_provider_returns_false(db_session):
    p = _project(db_session)
    result = delete_secret(db_session, project_id=p.id, provider="nonexistent")
    assert result is False


def test_get_decrypted_secrets_empty_project(db_session):
    p = _project(db_session)
    secrets = get_decrypted_secrets(db_session, p.id)
    assert secrets == {}


def test_get_decrypted_secrets_missing_key_raises_secret_key_missing(monkeypatch, db_session):
    p = _project(db_session)
    # set_secret works while the key is still in env
    set_secret(db_session, project_id=p.id, provider="openai", plaintext="sk-test")
    # now remove the key so decrypt cannot proceed
    monkeypatch.delenv("TOKENSURF_SECRET_KEY", raising=False)
    from tokensurf_server.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(SecretKeyMissing):
        get_decrypted_secrets(db_session, p.id)
