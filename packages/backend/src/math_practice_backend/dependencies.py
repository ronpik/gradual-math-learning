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

from fastapi import Depends, Header
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from .auth import (
    AuthError,
    AuthIdentity,
    AuthProvider,
    FirebaseAuthProvider,
)
from .clock import Clock, RealClock
from .db import engine as default_engine
from .db import session_factory as default_session_factory
from .identity_service import IdentityService
from .repositories import (
    LearnerRepository,
    SessionRepository,
    SqlAlchemyLearnerRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
    UserRepository,
)
from .service import ProgressService, SessionService, StatsService
from .settings import Settings, get_settings


@dataclass
class _AppState:
    """Process-wide shared singletons for the HTTP layer.

    Attributes:
        repository:         the shared session repository (built once).
        learner_repository: the shared learner/module-progress repository (built
                            once).
        user_repository:    the shared user-account repository (built once).
        progress_service:   the shared learner-identity + progress service.
        stats_service:      the shared read-only reporting service.
        service:            the shared session service (built once).
        clock:              the shared clock used by the service and sweeper.
    """

    repository: SessionRepository | None = None
    learner_repository: LearnerRepository | None = None
    user_repository: UserRepository | None = None
    progress_service: ProgressService | None = None
    stats_service: StatsService | None = None
    service: SessionService | None = None
    clock: Clock | None = None
    auth_provider: AuthProvider | None = None
    identity_service: IdentityService | None = None


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


def get_learner_repository() -> LearnerRepository:
    """Return the shared :class:`LearnerRepository`, building it once.

    Backed by :class:`SqlAlchemyLearnerRepository` over the shared session
    factory. Split from the session repository because learners and their
    cross-session module progress are a permanent aggregate with a different
    lifetime than the ephemeral 24h session.
    """
    if _state.learner_repository is None:
        _state.learner_repository = SqlAlchemyLearnerRepository(
            get_session_factory()
        )
    return _state.learner_repository


def get_user_repository() -> UserRepository:
    """Return the shared :class:`UserRepository`, building it once.

    Backed by :class:`SqlAlchemyUserRepository` over the shared session factory.
    A user (Firebase uid as id) owns zero or more learners via the learners'
    optional ``user_id``; no auth verification is wired in this step.
    """
    if _state.user_repository is None:
        _state.user_repository = SqlAlchemyUserRepository(get_session_factory())
    return _state.user_repository


def get_progress_service() -> ProgressService:
    """Return the shared :class:`ProgressService`, building it once.

    Owns learner identity + cross-session :class:`ModuleProgress`; wraps the
    shared learner repository.
    """
    if _state.progress_service is None:
        _state.progress_service = ProgressService(
            learner_repo=get_learner_repository(),
        )
    return _state.progress_service


def get_stats_service() -> StatsService:
    """Return the shared :class:`StatsService`, building it once.

    Owns read-only reporting (stats, summary, streak); wraps the shared session
    repository.
    """
    if _state.stats_service is None:
        _state.stats_service = StatsService(repo=get_repository())
    return _state.stats_service


def get_service() -> SessionService:
    """Return the shared :class:`SessionService`, building it once.

    The session service is configured with the shared session repository, the
    shared :class:`ProgressService` (which it delegates learner + progress
    seeding and write-through to), a :class:`RealClock`, and a sliding TTL of
    ``settings.session_ttl_hours`` hours.
    """
    if _state.service is None:
        settings: Settings = get_settings()
        _state.service = SessionService(
            repo=get_repository(),
            progress_service=get_progress_service(),
            clock=get_clock(),
            ttl=timedelta(hours=settings.session_ttl_hours),
        )
    return _state.service


def get_auth_provider() -> AuthProvider:
    """Return the shared :class:`AuthProvider`, building it once.

    Uses :class:`FirebaseAuthProvider` when ``settings.firebase_project_id`` is
    set. With no project id configured the provider cannot verify tokens, so a
    placeholder that always 401s is returned (tests override this dependency
    with a :class:`~math_practice_backend.auth.FakeAuthProvider`).
    """
    if _state.auth_provider is None:
        settings: Settings = get_settings()
        if settings.firebase_project_id:
            _state.auth_provider = FirebaseAuthProvider(
                settings.firebase_project_id
            )
        else:
            _state.auth_provider = _UnconfiguredAuthProvider()
    return _state.auth_provider


def get_identity_service() -> IdentityService:
    """Return the shared :class:`IdentityService`, building it once.

    Receives the user and learner repositories (ABCs) and the shared clock; it
    performs no token verification (that is the auth provider's job).
    """
    if _state.identity_service is None:
        _state.identity_service = IdentityService(
            user_repo=get_user_repository(),
            learner_repo=get_learner_repository(),
            clock=get_clock(),
        )
    return _state.identity_service


class _UnconfiguredAuthProvider(AuthProvider):
    """Fallback provider used when no Firebase project id is configured.

    Any verification attempt raises :class:`AuthError` (mapped to ``401``), so a
    misconfigured deployment fails closed rather than accepting tokens it cannot
    verify.
    """

    def verify(self, token: str) -> AuthIdentity:  # noqa: D102
        raise AuthError("Authentication is not configured")


def _extract_bearer(authorization: str | None) -> str | None:
    """Return the bearer token from an ``Authorization`` header, or ``None``.

    ``None`` (header absent) is returned unchanged. A present-but-malformed
    header (not ``Bearer <token>``) raises :class:`AuthError`.
    """
    if authorization is None:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Malformed Authorization header")
    return parts[1].strip()


def get_optional_identity(
    authorization: str | None = Header(default=None),
    provider: AuthProvider = Depends(get_auth_provider),
) -> AuthIdentity | None:
    """Resolve an optional caller identity from the ``Authorization`` header.

    Returns ``None`` when no header is present (anonymous play). When a header
    *is* present it must be a valid ``Bearer <token>``; a missing/invalid/expired
    token raises :class:`AuthError` (``401``). The provider is injected via
    :func:`get_auth_provider` so tests can override it.
    """
    token = _extract_bearer(authorization)
    if token is None:
        return None
    return provider.verify(token)


def get_required_identity(
    authorization: str | None = Header(default=None),
    provider: AuthProvider = Depends(get_auth_provider),
) -> AuthIdentity:
    """Resolve a required caller identity from the ``Authorization`` header.

    Raises :class:`AuthError` (``401``) when the header is absent, malformed, or
    carries an invalid/expired token. The provider is injected via
    :func:`get_auth_provider` so tests can override it.
    """
    token = _extract_bearer(authorization)
    if token is None:
        raise AuthError("Missing Authorization header")
    return provider.verify(token)
