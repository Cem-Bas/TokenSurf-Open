import hashlib

from tokensurf_server.security import generate_api_key, hash_key, key_prefix, verify_key


def test_generate_api_key_has_tsk_prefix() -> None:
    key = generate_api_key()
    assert key.startswith("tsk_")


def test_generate_api_key_is_unique() -> None:
    assert generate_api_key() != generate_api_key()


def test_key_prefix_length() -> None:
    key = generate_api_key()
    assert len(key_prefix(key)) == 11


def test_key_prefix_equals_first_eleven_chars() -> None:
    key = generate_api_key()
    assert key_prefix(key) == key[:11]


def test_hash_key_is_stable() -> None:
    raw = "tsk_testkey_stability_check"
    assert hash_key(raw) == hash_key(raw)


def test_hash_key_is_sha256_hex() -> None:
    raw = "tsk_testkey_sha256_check"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert hash_key(raw) == expected


def test_verify_key_returns_true_on_matching_hash() -> None:
    raw = generate_api_key()
    assert verify_key(raw, hash_key(raw)) is True


def test_verify_key_returns_false_on_wrong_hash() -> None:
    raw = generate_api_key()
    other = generate_api_key()
    assert verify_key(raw, hash_key(other)) is False


def test_verify_key_returns_false_on_tampered_key() -> None:
    raw = generate_api_key()
    h = hash_key(raw)
    assert verify_key(raw + "x", h) is False
