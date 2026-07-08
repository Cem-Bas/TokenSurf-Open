import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tokensurf_server.config import get_settings
from tokensurf_server.db import get_engine, get_session, get_sessionmaker
from tokensurf_server.ingest import router
from tokensurf_server.models import User
from tokensurf_server.security_config import _parse_bool_env, validate_security_config
from tokensurf_server.setup_token import get_or_create_token
from tokensurf_server.web.csrf import CsrfMiddleware
from tokensurf_server.web.routes import router as web_router

log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "web" / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail loudly at startup (spec §8): missing/invalid DATABASE_URL surfaces here.
    settings = get_settings()
    get_engine()
    # Spec §8/§10: the dashboard signs session cookies with session_secret.
    # validate_security_config enforces a minimum length and rejects the built-in
    # default unless the insecure bypass flag is set to a truthy value
    # ("1"/"true"/"yes"/"on"). Local/test runs opt in explicitly via
    # TOKENSURF_ALLOW_INSECURE_SESSION_SECRET=1 (conftest sets it).
    validate_security_config(
        settings,
        allow_insecure=_parse_bool_env(os.environ.get("TOKENSURF_ALLOW_INSECURE_SESSION_SECRET")),
    )
    with get_sessionmaker()() as session:
        user_count = session.scalar(select(func.count(User.id))) or 0
    if user_count == 0:
        get_or_create_token(Path(settings.setup_token_path))
        log.info(
            "First-run setup: create the admin account at http://%s:%s/setup using the token in %s",
            settings.host,
            settings.port,
            settings.setup_token_path,
        )
    yield


def create_app() -> FastAPI:
    # Move the auto-generated OpenAPI/Swagger UI off "/docs" so that path is free
    # for the product's own Docs page (web router). The API docs live at /api/docs.
    app = FastAPI(
        title="TokenSurf Server",
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.add_middleware(CsrfMiddleware)
    app.include_router(router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    def healthz(session: Session = Depends(get_session)) -> dict:  # noqa: B008
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
