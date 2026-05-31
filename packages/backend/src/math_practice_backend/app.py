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
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
from .settings import get_settings
from .sweeper import sweeper_loop


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
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="math-practice-backend", lifespan=lifespan)
app.include_router(router)


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
