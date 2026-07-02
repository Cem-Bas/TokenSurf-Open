"""FastAPI web (HTML) router — dashboard pages.

All chart strings are pre-rendered server-side and passed to templates; only
those values are rendered with |safe in Jinja2 (they contain numbers only).
All other context variables (labels, case input/output, trace) are autoescaped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

import tokensurf_server.notify as _notify
from tokensurf_server import audit_service as audit_service
from tokensurf_server.auth import SESSION_COOKIE, login_required, make_session
from tokensurf_server.config import get_settings
from tokensurf_server.crypto import encrypt
from tokensurf_server.db import get_session
from tokensurf_server.models import NotificationChannel, Project, QualityGate, User
from tokensurf_server.ratelimit import SlidingWindowLimiter, parse_rate
from tokensurf_server.security import hash_password, verify_password
from tokensurf_server.web.charts import distribution_bars, trend_svg
from tokensurf_server.web.csrf import CSRF_COOKIE
from tokensurf_server.web.csrf import verify as verify_csrf
from tokensurf_server.web.queries import (
    list_all_runs,
    list_channels,
    list_gates,
    list_projects_with_summary,
    list_secrets,
    project_overview,
    run_detail,
)

log = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Brute-force throttles for POST /login. One keyed on client IP (blocks a single noisy
# source) and one keyed on the submitted account (blocks a distributed guess against one
# email even when the attacker rotates source IPs). Captured at import like the config
# limiter; tests reset both via the _reset_rate_limiters conftest fixture.
_login_count, _login_window = parse_rate(get_settings().login_rate_limit)
_login_limiter = SlidingWindowLimiter(_login_count, _login_window)
_login_email_limiter = SlidingWindowLimiter(_login_count, _login_window)

# Precomputed once so login does the same PBKDF2 work whether or not the email
# exists — closing the timing oracle that would otherwise enumerate valid emails.
_DUMMY_PASSWORD_HASH = hash_password("tokensurf-no-such-user")

# Synthetic run used for test-send notifications (no real DB run needed).
# project_id is included so webhook notifiers (which embed run.project_id in the
# payload) do not AttributeError during test-send.  (BINDING CORRECTION #7)
_TEST_SEND_RUN = SimpleNamespace(
    id="test-send",
    project_id="test-send",
    label="Test notification",
    pass_rate=1.0,
    status="test",
)


def _require_csrf(request: Request, csrf_token: str) -> None:
    """Raise HTTP 403 if the CSRF double-submit check fails."""
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not verify_csrf(cookie_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid or missing")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def get_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def post_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(default=""),
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    # Guard against login CSRF (an attacker forcing a victim into an attacker-chosen
    # session). The CsrfMiddleware issues the ts_csrf cookie + token on GET /login.
    _require_csrf(request, csrf_token)
    # Throttle password brute-force per client IP AND per account. (Behind a proxy the IP
    # key is the proxy IP unless trusted-proxy handling is enabled — see docs/security.md.)
    client_ip = request.client.host if request.client else "unknown"
    email_key = email.strip().lower()
    ip_ok = _login_limiter.allow(client_ip)
    email_ok = _login_email_limiter.allow(email_key)
    if not (ip_ok and email_ok):
        retry = max(
            _login_limiter.retry_after(client_ip),
            _login_email_limiter.retry_after(email_key),
        )
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry)},
        )
    user = session.scalar(select(User).where(User.email == email))
    expected_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, expected_hash)
    if user is None or not password_ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password"},
            status_code=401,
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        make_session(user.id),
        httponly=True,
        samesite="lax",
        secure=get_settings().secure_cookies,
    )
    return resp


@router.post("/logout")
def post_logout(
    request: Request,
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Dashboard routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def projects_list(
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    projects = list_projects_with_summary(session)
    return templates.TemplateResponse(
        request,
        "projects.html",
        {"user": user, "projects": projects},
    )


@router.get("/runs", response_class=HTMLResponse)
def runs_list(
    request: Request,
    project: str | None = None,
    gate: str | None = None,
    page: int = 1,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    page = max(1, page)
    limit = 25
    rows, total = list_all_runs(
        session,
        project_slug=project or None,
        gate_status=gate if gate in ("failed", "passed") else None,
        limit=limit,
        offset=(page - 1) * limit,
    )
    projects = list_projects_with_summary(session)
    pages = max(1, (total + limit - 1) // limit)
    return templates.TemplateResponse(
        request,
        "runs.html",
        {
            "user": user,
            "rows": rows,
            "projects": projects,
            "total": total,
            "page": page,
            "pages": pages,
            "sel_project": project or "",
            "sel_gate": gate or "",
        },
    )


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
) -> HTMLResponse:
    return templates.TemplateResponse(request, "docs.html", {"user": user})


@router.get("/scorers", response_class=HTMLResponse)
def scorers_reference(
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
) -> HTMLResponse:
    return templates.TemplateResponse(request, "scorers.html", {"user": user})


@router.get("/projects/{slug}", response_class=HTMLResponse)
def project_detail(
    slug: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    overview = project_overview(session, slug)
    if overview is None:
        raise HTTPException(status_code=404)
    svg = trend_svg(overview.passrates)
    return templates.TemplateResponse(
        request,
        "project.html",
        {"user": user, "overview": overview, "trend_svg": svg},
    )


@router.get("/projects/{slug}/runs/{run_id}", response_class=HTMLResponse)
def run_detail_view(
    slug: str,
    run_id: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    detail = run_detail(session, run_id, slug)
    if detail is None:
        raise HTTPException(status_code=404)
    for stat in detail.scorer_stats:
        stat.bars_html = distribution_bars(stat.distribution)
    return templates.TemplateResponse(
        request,
        "run.html",
        {"user": user, "detail": detail},
    )


# ---------------------------------------------------------------------------
# Settings routes — all login_required; state-changing POSTs CSRF-verified
# ---------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def settings_index(
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> HTMLResponse:
    """Project picker: list all projects linking to their per-project settings page."""
    projects = list_projects_with_summary(session)
    return templates.TemplateResponse(
        request,
        "settings_index.html",
        {"user": user, "projects": projects},
    )


@router.get("/settings/{slug}", response_class=HTMLResponse)
def settings_detail(
    slug: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> Response:
    """Per-project settings page — gates + channels + CRUD forms. CSRF token from middleware."""
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    gates = list_gates(session, slug) or []
    channels = list_channels(session, slug) or []
    activity = audit_service.recent(session, proj.id, limit=20)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "slug": slug,
            "name": proj.name,
            "gates": gates,
            "channels": channels,
            "secrets": list_secrets(session, slug) or [],
            "csrf_token": request.state.csrf_token,
            "activity": activity,
        },
    )


@router.post("/settings/{slug}/gates")
def settings_create_gate(
    slug: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    name: str = Form(...),
    metric: str = Form(...),
    scorer: str = Form(default=""),
    comparison: str = Form(default="gte"),
    threshold: float = Form(...),
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    gate = QualityGate(
        project_id=proj.id,
        name=name,
        metric=metric,
        scorer=scorer.strip() or None,
        comparison=comparison,
        threshold=threshold,
        enabled=True,
    )
    session.add(gate)
    session.commit()
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/gates/{gate_id}/delete")
def settings_delete_gate(
    slug: str,
    gate_id: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    gate = session.scalar(
        select(QualityGate).where(QualityGate.id == gate_id, QualityGate.project_id == proj.id)
    )
    if gate is not None:
        session.delete(gate)
        session.commit()
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/channels")
def settings_create_channel(
    slug: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    name: str = Form(...),
    type: str = Form(...),  # noqa: A002
    secret: str = Form(...),
    to: str = Form(default=""),
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    config = {"to": to} if to.strip() else None
    channel = NotificationChannel(
        project_id=proj.id,
        type=type,
        name=name,
        secret_enc=encrypt(secret),
        config=config,
        enabled=True,
    )
    session.add(channel)
    session.commit()
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/channels/{channel_id}/delete")
def settings_delete_channel(
    slug: str,
    channel_id: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    channel = session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.project_id == proj.id,
        )
    )
    if channel is not None:
        session.delete(channel)
        session.commit()
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/channels/{channel_id}/test")
def settings_test_channel(
    slug: str,
    channel_id: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    csrf_token: str = Form(default=""),
) -> Response:
    """Fire a synthetic test notification for the channel. Best-effort: never 500."""
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    channel = session.scalar(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.project_id == proj.id,
        )
    )
    if channel is None:
        raise HTTPException(status_code=404)
    try:
        notifier = _notify.get_notifier(channel.type)
        notifier.send(run=_TEST_SEND_RUN, failed_gates=[], channel=channel)
    except Exception as exc:
        log.warning(
            "Test-send failed for channel %s (project %s): %s",
            channel_id,
            slug,
            type(exc).__name__,
        )
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/secrets")
def settings_create_secret(
    slug: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    provider: str = Form(...),
    secret: str = Form(...),
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    from tokensurf_server.secrets_service import set_secret

    set_secret(session, project_id=proj.id, provider=provider, plaintext=secret)
    session.commit()
    try:
        audit_service.record(
            session,
            event="secret.set",
            project_id=proj.id,
            actor=f"user:{user.email}",
            detail={"provider": provider},
        )
        session.commit()
    except Exception as exc:
        log.warning("audit secret.set failed for project %s: %s", proj.id, type(exc).__name__)
    return RedirectResponse(f"/settings/{slug}", status_code=303)


@router.post("/settings/{slug}/secrets/{provider}/delete")
def settings_delete_secret(
    slug: str,
    provider: str,
    request: Request,
    user: User = Depends(login_required),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
    csrf_token: str = Form(default=""),
) -> Response:
    _require_csrf(request, csrf_token)
    proj = session.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        raise HTTPException(status_code=404)
    from tokensurf_server.secrets_service import delete_secret

    delete_secret(session, project_id=proj.id, provider=provider)
    session.commit()
    try:
        audit_service.record(
            session,
            event="secret.delete",
            project_id=proj.id,
            actor=f"user:{user.email}",
            detail={"provider": provider},
        )
        session.commit()
    except Exception as exc:
        log.warning("audit secret.delete failed for project %s: %s", proj.id, type(exc).__name__)
    return RedirectResponse(f"/settings/{slug}", status_code=303)
