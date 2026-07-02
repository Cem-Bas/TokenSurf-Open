"""CSRF double-submit token helpers.

Pattern: on GET, issue a signed token, set it as the ts_csrf cookie AND embed it
in the page as a hidden form field (csrf_token).  On every state-changing POST,
call verify(request.cookies.get(CSRF_COOKIE), form_csrf_token); reject with 403
if it returns False.

Security properties:
- Tokens are signed with the same session_secret used for sessions (different salt
  so tokens are not interchangeable).
- Double-submit means the attacker must be able to read the cookie to forge a
  request — browsers enforce same-origin cookie access, so this is sufficient
  against CSRF from foreign origins.
- Each GET issues a fresh token (new random ID), so tokens do not accumulate.

CsrfMiddleware guarantees every response carries a ts_csrf cookie and exposes
request.state.csrf_token so any template can embed it in a hidden field without
the individual route needing to call issue_token() or set_cookie().
"""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from tokensurf.core.ids import new_id

from tokensurf_server.config import get_settings

CSRF_COOKIE = "ts_csrf"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="ts-csrf")


def issue_token() -> str:
    """Return a newly-signed CSRF token encoding a fresh random ID."""
    return _serializer().dumps(new_id())


def verify(cookie_token: str | None, form_token: str | None) -> bool:
    """Return True iff both tokens are present, validly signed, and encode the same value.

    Any of the following returns False:
    - Either argument is None.
    - Either token has an invalid or tampered signature.
    - The two tokens encode different underlying IDs.
    """
    if cookie_token is None or form_token is None:
        return False
    ser = _serializer()
    try:
        cookie_val = ser.loads(cookie_token)
        form_val = ser.loads(form_token)
    except BadSignature:
        return False
    return cookie_val == form_val


class CsrfMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that guarantees every response carries a ts_csrf cookie.

    On every request:
    - If the ts_csrf cookie is present AND validly signed, reuse its value as the token.
    - Otherwise (absent, tampered, or signed with a rotated secret) issue a fresh token,
      so a bad cookie self-heals on the next page load instead of locking the browser
      out of every state-changing POST forever.
    - Set request.state.csrf_token so templates can embed it without calling issue_token().
    - Re-emit Set-Cookie: ts_csrf=<token> on every HTML response. The value is stable
      (equal to the incoming cookie when it verifies), so a valid token is never
      *changed* — but re-emitting makes the cookie observable on every response,
      which the double-submit tests (and clients that lost the cookie) rely on.

    The cookie is emitted ONLY on HTML responses (content-type text/html) — the pages
    that render CSRF-bearing forms. JSON APIs (/api/*, /healthz, /openapi.json) and
    static assets never carry it, so it is not header noise and cannot defeat CDN
    caching of static files. The Secure flag follows settings.secure_cookies.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        cookie = request.cookies.get(CSRF_COOKIE)
        if cookie is not None:
            # Re-issue rather than propagate an unverifiable cookie (tampered, or
            # signed with a previous session_secret after rotation).
            try:
                _serializer().loads(cookie)
            except BadSignature:
                cookie = None
        token = cookie or issue_token()
        # Always exposed to templates (so forms can embed it); only the Set-Cookie is gated.
        request.state.csrf_token = token
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("text/html"):
            # Value-preserving when the incoming cookie verified; observable as Set-Cookie
            # on every HTML response the double-submit forms depend on.
            response.set_cookie(
                CSRF_COOKIE,
                token,
                httponly=False,
                samesite="lax",
                secure=get_settings().secure_cookies,
            )
        return response
