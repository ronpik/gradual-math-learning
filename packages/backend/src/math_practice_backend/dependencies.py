"""FastAPI dependency-injection providers.

Wires the runtime object graph for the HTTP layer: settings, the (shared)
SQLAlchemy engine + session factory, the repository, and the session service.

The repository and service are built once and shared for the whole application
lifetime. They are stateless apart from the service's per-session lock table, so
a single instance is safe to reuse across requests; this also keeps the
in-memory SQLite engine (and its :class:`~sqlalchemy.pool.StaticPool`) stable.

These providers are plain callables usable both as FastAPI ``Depends`` targets
and directly (e.g. from the lifespan/sweeper). The shared singletons live in
:data:`_state`, populated lazily on first use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from .clock import Clock, RealClock
from .db import engine as default_engine
from .db import session_factory as default_session_factory
from .repositories import SessionRepository, SqlAlchemySessionRepository
from .service import SessionService
from .settings import Settings, get_settings


@dataclass
class _AppState:
    """Process-wide shared singletons for the HTTP layer.

    Attributes:
        repository: the shared session repository (built once).
        service:    the shared session service (built once).
        clock:      the shared clock used by the service and sweeper.
    """

    repository: SessionRepository | None = None
    service: SessionService | None = None
    clock: Clock | None = None


#: Lazily-populated container for the application's shared singletons.
_state = _AppState()


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine (singleton from :mod:`db`)."""
    return default_engine


def get_session_factory() -> sessionmaker:
    """Return the process-wide session factory (singleton from :mod:`db`)."""
    return default_session_factory


def get_clock() -> Clock:
    """Return the shared :class:`Clock`, creating a :class:`RealClock` once."""
    if _state.clock is None:
        _state.clock = RealClock()
    return _state.clock


def get_repository() -> SessionRepository:
    """Return the shared :class:`SessionRepository`, building it once.

    Backed by :class:`SqlAlchemySessionRepository` over the shared session
    factory.
    """
    if _state.repository is None:
        _state.repository = SqlAlchemySessionRepository(get_session_factory())
    return _state.repository


def get_service() -> SessionService:
    """Return the shared :class:`SessionService`, building it once.

    The service is configured with the shared repository, a :class:`RealClock`,
    and a sliding TTL of ``settings.session_ttl_hours`` hours.
    """
    if _state.service is None:
        settings: Settings = get_settings()
        _state.service = SessionService(
            repo=get_repository(),
            clock=get_clock(),
            ttl=timedelta(hours=settings.session_ttl_hours),
        )
    return _state.service
