"""Tests for the first-run setup-token file (Jenkins-style initialAdminPassword)."""

from __future__ import annotations

from pathlib import Path

from tokensurf_server.setup_token import get_or_create_token


def test_creates_token_file_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "setup_token"
    assert not path.exists()
    token = get_or_create_token(path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip() == token
    assert len(token) > 16


def test_reuses_existing_token_file(tmp_path: Path) -> None:
    path = tmp_path / "setup_token"
    first = get_or_create_token(path)
    second = get_or_create_token(path)
    assert first == second


def test_token_file_is_not_world_readable(tmp_path: Path) -> None:
    path = tmp_path / "setup_token"
    get_or_create_token(path)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
