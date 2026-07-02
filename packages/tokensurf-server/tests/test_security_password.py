from __future__ import annotations


def test_hash_password_returns_pbkdf2_format() -> None:
    """Output has exactly four $-delimited parts: algo, iterations, salt_hex, dk_hex."""
    from tokensurf_server.security import hash_password

    stored = hash_password("correct-horse-battery-staple")
    parts = stored.split("$")
    assert len(parts) == 4, f"expected 4 parts, got: {parts}"
    assert parts[0] == "pbkdf2"
    assert int(parts[1]) == 240_000


def test_verify_password_correct_round_trip() -> None:
    from tokensurf_server.security import hash_password, verify_password

    pw = "correct-horse-battery-staple"
    assert verify_password(pw, hash_password(pw)) is True


def test_verify_password_wrong_password() -> None:
    from tokensurf_server.security import hash_password, verify_password

    stored = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", stored) is False


def test_verify_password_malformed_stored_returns_false() -> None:
    """Any stored string that cannot be parsed returns False without raising."""
    from tokensurf_server.security import verify_password

    assert verify_password("any", "not$valid") is False  # only 2 parts
    assert verify_password("any", "") is False  # empty string
    assert verify_password("any", "a$b$c$not-hex") is False  # invalid hex in salt


def test_hash_password_unique_salts() -> None:
    """Two calls with the same password produce different stored strings."""
    from tokensurf_server.security import hash_password

    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
