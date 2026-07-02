"""Session helpers: signed cookie, FastAPI dependencies for authentication."""

from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from tokensurf_server.config import get_settings
from tokensurf_server.db import get_session
from tokensurf_server.models import User

SESSION_COOKIE = "ts_session"

# Valid itsdangerous URL-safe token chars: base64url alphabet + separator dot.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-=.]+$")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="ts-session")


def make_session(user_id: str) -> str:
    """Return an itsdangerous-signed token encoding user_id."""
    return _serializer().dumps(user_id)


def read_session(token: str | None) -> str | None:
    """Return user_id from a valid signed token, or None on bad or missing input."""
    if token is None:
        return None
    # Reject tokens that contain characters outside the URL-safe base64 alphabet.
    # Python's base64 decoder silently strips unknown chars; validating first
    # ensures an attacker cannot smuggle bytes past the HMAC check.
    if not _SAFE_TOKEN_RE.match(token):
        return None
    try:
        return _serializer().loads(token)
    except BadSignature:
        return None


def current_user(
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008
) -> User | None:
    """FastAPI dependency: resolve the session cookie to a User row, or None."""
    uid = read_session(request.cookies.get(SESSION_COOKIE))
    if uid is None:
        return None
    return session.get(User, uid)


def login_required(user: User | None = Depends(current_user)) -> User:  # noqa: B008
    """FastAPI dependency: require an authenticated user or redirect to /login."""
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user
