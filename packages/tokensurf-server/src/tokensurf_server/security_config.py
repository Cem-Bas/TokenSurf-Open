"""Session-secret guard — unit-testable validation (H3).

Extracted from app.py lifespan so the logic can be tested without
booting the full application.
"""

from __future__ import annotations

from tokensurf_server.config import INSECURE_SESSION_SECRET_DEFAULT, MIN_SESSION_SECRET_LEN


def _parse_bool_env(value: str | None) -> bool:
    """Return True only when value.strip().lower() is in {"1", "true", "yes", "on"}.

    All other inputs — including None, "", "0", "false", "no", "off" — return False.
    This stricter parse replaces the previous ``if os.environ.get(...)`` pattern
    that treated any non-empty string (including "0") as truthy.
    """
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_security_config(settings: object, *, allow_insecure: bool) -> None:
    """Raise RuntimeError when the session secret is insecure and allow_insecure is False.

    Passes silently when:
    - allow_insecure is True (local / test override), OR
    - settings.session_secret is at least MIN_SESSION_SECRET_LEN chars long and
      is not the built-in INSECURE_SESSION_SECRET_DEFAULT.

    ``settings`` is typed as ``object`` so pure-unit tests can pass a SimpleNamespace
    without importing the full Settings class.
    """
    if allow_insecure:
        return

    secret: str = settings.session_secret  # type: ignore[attr-defined]
    if secret == INSECURE_SESSION_SECRET_DEFAULT or len(secret) < MIN_SESSION_SECRET_LEN:
        raise RuntimeError(
            "Refusing to serve with an insecure session secret. "
            "Set TOKENSURF_SESSION_SECRET to a random string of at least "
            f"{MIN_SESSION_SECRET_LEN} characters "
            "(or set TOKENSURF_ALLOW_INSECURE_SESSION_SECRET=1 for local/test only)."
        )
