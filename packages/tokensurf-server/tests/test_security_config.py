"""Pure-unit tests for security_config.py — _parse_bool_env and
validate_security_config.  No DB, no app startup required.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _fake_settings(session_secret: str) -> object:
    return SimpleNamespace(session_secret=session_secret)


class TestParseBoolEnv:
    def test_none_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env(None) is False

    def test_empty_string_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("") is False

    def test_zero_string_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("0") is False

    def test_false_lowercase_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("false") is False

    def test_False_mixed_case_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("False") is False

    def test_no_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("no") is False

    def test_off_returns_false(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("off") is False

    def test_one_returns_true(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("1") is True

    def test_true_lowercase_returns_true(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("true") is True

    def test_True_mixed_case_returns_true(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("True") is True

    def test_YES_uppercase_returns_true(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("YES") is True

    def test_on_returns_true(self) -> None:
        from tokensurf_server.security_config import _parse_bool_env

        assert _parse_bool_env("on") is True


class TestValidateSecurityConfig:
    def test_default_secret_raises_runtime_error(self) -> None:
        from tokensurf_server.config import INSECURE_SESSION_SECRET_DEFAULT
        from tokensurf_server.security_config import validate_security_config

        with pytest.raises(RuntimeError, match="TOKENSURF_SESSION_SECRET"):
            validate_security_config(
                _fake_settings(INSECURE_SESSION_SECRET_DEFAULT), allow_insecure=False
            )

    def test_short_custom_secret_raises_runtime_error(self) -> None:
        from tokensurf_server.security_config import validate_security_config

        with pytest.raises(RuntimeError, match="TOKENSURF_SESSION_SECRET"):
            validate_security_config(_fake_settings("too-short"), allow_insecure=False)

    def test_secret_at_minimum_length_passes(self) -> None:
        from tokensurf_server.security_config import validate_security_config

        # Exactly 32 characters — at the boundary; must not raise.
        validate_security_config(_fake_settings("a" * 32), allow_insecure=False)

    def test_secret_above_minimum_length_passes(self) -> None:
        from tokensurf_server.security_config import validate_security_config

        validate_security_config(_fake_settings("a" * 64), allow_insecure=False)

    def test_allow_insecure_bypasses_default_secret(self) -> None:
        from tokensurf_server.config import INSECURE_SESSION_SECRET_DEFAULT
        from tokensurf_server.security_config import validate_security_config

        # Must not raise even with the built-in insecure default.
        validate_security_config(
            _fake_settings(INSECURE_SESSION_SECRET_DEFAULT), allow_insecure=True
        )

    def test_allow_insecure_bypasses_short_secret(self) -> None:
        from tokensurf_server.security_config import validate_security_config

        # Must not raise even with a 1-char secret.
        validate_security_config(_fake_settings("x"), allow_insecure=True)
