"""FastAPI application for the math-practice backend.

Composes the ASGI app: it includes the HTTP router, registers exception
handlers mapping service-layer errors to status codes, and runs a lifespan that
initialises the database schema and starts/stops the background expiry sweeper.

Service-layer error mapping:

    * :class:`SessionNotFound`   -> 404
    * :class:`SessionExpired`    -> 410
    * :class:`NoPendingExercise` -> 409
    * :class:`InvalidConfig`     -> 422

All error responses share the shape ``{"detail": <message>}``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .dependencies import get_clock, get_repository, get_service
from .errors import (
    InvalidConfig,
    NoPendingExercise,
    ServiceError,
    SessionExpired,
    SessionNotFound,
)
from .routes import router
from .routes_play import router as play_router
from .settings import Settings, get_settings
from .sweeper import sweeper_loop


def _resolve_web_dir(settings: Settings) -> Path:
    """Resolve the directory holding the built static web client.

    Honours ``settings.web_dir`` when set; otherwise defaults to
    ``<repo_root>/packages/web-client-static/dist`` where ``repo_root`` is four
    parents above this module.
    """
    if settings.web_dir is not None:
        return Path(settings.web_dir)
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "packages" / "web-client-static" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: init schema + run the expiry sweeper.

    On startup the database schema is created, the shared repository/service are
    eagerly built, and the background sweeper task is launched. On shutdown the
    sweeper task is cancelled and awaited.
    """
    init_db()
    # Eagerly build the shared singletons so the sweeper and request handlers
    # share the same repository/service instances.
    repo = get_repository()
    get_service()
    settings = get_settings()

    sweeper_task = asyncio.create_task(
        sweeper_loop(
            repo=repo,
            clock=get_clock(),
            interval_seconds=settings.sweeper_interval_seconds,
        )
    )

    # Mount the static web client LAST so the explicit ``/health`` and ``/v1/*``
    # routes (already registered on the app) always take precedence over the
    # catch-all mount at "/". Skip silently if serving is disabled or the build
    # directory does not exist yet (the server must run before the frontend is
    # built).
    if settings.serve_web:
        web_dir = _resolve_web_dir(settings)
        if web_dir.is_dir():
            app.mount(
                "/",
                StaticFiles(directory=str(web_dir), html=True),
                name="web",
            )

    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="math-practice-backend", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(play_router)


def _error_response(status_code: int, message: str) -> JSONResponse:
    """Build a ``{"detail": ...}`` JSON error response."""
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(SessionNotFound)
async def _handle_not_found(
    request: Request, exc: SessionNotFound
) -> JSONResponse:
    """Map :class:`SessionNotFound` to ``404 Not Found``."""
    return _error_response(404, exc.message)


@app.exception_handler(SessionExpired)
async def _handle_expired(
    request: Request, exc: SessionExpired
) -> JSONResponse:
    """Map :class:`SessionExpired` to ``410 Gone``."""
    return _error_response(410, exc.message)


@app.exception_handler(NoPendingExercise)
async def _handle_no_pending(
    request: Request, exc: NoPendingExercise
) -> JSONResponse:
    """Map :class:`NoPendingExercise` to ``409 Conflict``."""
    return _error_response(409, exc.message)


@app.exception_handler(InvalidConfig)
async def _handle_invalid_config(
    request: Request, exc: InvalidConfig
) -> JSONResponse:
    """Map :class:`InvalidConfig` to ``422 Unprocessable Entity``."""
    return _error_response(422, exc.message)


@app.exception_handler(ServiceError)
async def _handle_service_error(
    request: Request, exc: ServiceError
) -> JSONResponse:
    """Fallback for any unmapped service error -> ``400 Bad Request``."""
    return _error_response(400, exc.message)
