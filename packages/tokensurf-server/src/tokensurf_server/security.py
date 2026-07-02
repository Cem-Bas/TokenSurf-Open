import hashlib
import secrets

_PBKDF2_ITER = 240_000


def generate_api_key() -> str:
    """Generate a new random ingest API key with the tsk_ prefix."""
    return "tsk_" + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest of raw. Used for at-rest storage."""
    return hashlib.sha256(raw.encode()).hexdigest()


def key_prefix(raw: str) -> str:
    """Return the first 11 characters of raw for display / lookup."""
    return raw[:11]


def verify_key(raw: str, key_hash: str) -> bool:
    """Constant-time comparison: True when hash_key(raw) matches key_hash."""
    return secrets.compare_digest(hash_key(raw), key_hash)


def hash_password(password: str) -> str:
    """Return a pbkdf2-hmac-sha256 hash of password with a random 16-byte salt.

    Format: ``pbkdf2$<iterations>$<salt_hex>$<dk_hex>``
    Plaintext is never retained; each call uses a fresh salt.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return f"pbkdf2${_PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of password against a stored pbkdf2 hash.

    Returns False (never raises) on any malformed or None-like input.
    """
    try:
        _algo, iter_s, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iter_s))
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False
