from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf import EvalReport

import tokensurf_server.audit_service as audit_service
from tokensurf_server.config import get_settings
from tokensurf_server.db import get_session
from tokensurf_server.models import Project, ProjectApiKey, Run
from tokensurf_server.pipeline import evaluate_and_notify
from tokensurf_server.ratelimit import SlidingWindowLimiter, parse_rate
from tokensurf_server.schemas import ConfigResponse, IngestRunRequest, RunSummary
from tokensurf_server.security import hash_key
from tokensurf_server.service import persist_run, run_to_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# NOTE (spec §11): request body-size limiting is intentionally deferred to the
# reverse-proxy / deployment layer (and the hardening pass at security-review
# time), not enforced here in Slice 2a. No app-level cap is wired in this slice.

_cfg_count, _cfg_window = parse_rate(get_settings().config_rate_limit)
# NOTE (C1): _config_limiter is captured at import time; tests monkeypatch
# tokensurf_server.ingest._config_limiter directly (setting env after import is too late).
_config_limiter = SlidingWindowLimiter(_cfg_count, _cfg_window)


def get_project(
    request: Request,
    authorization: str = Header(default=""),
    session: Session = Depends(get_session),  # noqa: B008
) -> Project:
    """Resolve Bearer key to a Project; 401 on missing/malformed/unknown key.

    Stashes the resolved ProjectApiKey on request.state.api_key so downstream handlers
    (e.g. the config-pull audit) attribute actions to the key that actually authenticated
    this request, not a heuristic lookup.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="Empty API key")

    pak = session.scalar(select(ProjectApiKey).where(ProjectApiKey.key_hash == hash_key(raw_key)))
    if pak is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    pak.last_used_at = datetime.now(UTC)
    request.state.api_key = pak

    project = session.get(Project, pak.project_id)
    if project is None:
        raise HTTPException(status_code=401, detail="Project not found")
    return project


def _enforce_config_rate_limit(
    request: Request,
    project: Project = Depends(get_project),  # noqa: B008
) -> Project:
    """Rate-limit GET /api/v1/config per project; raises 429 + Retry-After on exceed."""
    if not _config_limiter.allow(project.id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(_config_limiter.retry_after(project.id))},
        )
    return project


@router.get("/config", response_model=ConfigResponse)
def get_config(
    request: Request,
    response: Response,
    project: Project = Depends(_enforce_config_rate_limit),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> ConfigResponse:
    from tokensurf_server.secrets_service import get_decrypted_secrets

    # SECURITY (spec §10 item 1): plaintext judge keys must never be cached by
    # proxies/CDNs/browsers. This endpoint is the ONLY place secrets leave the server.
    response.headers["Cache-Control"] = "no-store"
    judge_keys = get_decrypted_secrets(session, project.id)

    # Best-effort audit — never breaks the 200; config-pull delivery is what matters.
    # SECURITY: detail contains only key_count (an integer count), never a secret value.
    try:
        # Attribute to the key that actually authenticated this request (stashed by
        # get_project), not a most-recently-used heuristic.
        pak = getattr(request.state, "api_key", None)
        actor = f"api:{pak.key_prefix}" if pak else f"api:{project.id[:8]}"
        ip = request.client.host if request.client else None
        audit_service.record(
            session,
            event="config.pull",
            project_id=project.id,
            actor=actor,
            ip=ip,
            detail={"key_count": len(judge_keys)},
        )
        session.commit()
    except Exception:
        logger.warning("audit record failed for config.pull project=%s (non-fatal)", project.id[:8])

    return ConfigResponse(judge_keys=judge_keys)


@router.post("/runs", status_code=201, response_model=RunSummary)
def ingest_run(
    body: IngestRunRequest,
    project: Project = Depends(get_project),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> RunSummary:
    try:
        report = EvalReport(**body.report)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run = persist_run(
        session,
        project=project,
        report=report,
        label=body.label,
        metadata=body.metadata,
    )
    session.commit()

    # Best-effort gate evaluation + notifications. The run is ALREADY committed above;
    # this hook must never change the 201 or roll it back, so wrap it defensively here
    # (belt-and-suspenders even though evaluate_and_notify also guards internally — the
    # C3 resilience test monkeypatches evaluate_and_notify to raise and asserts 201).
    gate_results = []
    try:
        gate_results = evaluate_and_notify(session, project=project, run=run, report=report)
    except Exception:
        logger.exception("evaluate_and_notify failed for run %s (project %s)", run.id, project.slug)

    return run_to_summary(run, project.slug, gate_results=gate_results)


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(
    run_id: str,
    project: Project = Depends(get_project),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> RunSummary:
    run = session.get(Run, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_to_summary(run, project.slug)
