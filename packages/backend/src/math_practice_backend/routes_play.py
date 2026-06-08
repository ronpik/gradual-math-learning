"""Student-safe HTTP routes (the ``/v1/play`` API).

This router exposes the *only* surface the static web client talks to. Every
response is a ``Student*`` (or descriptor) schema that deliberately omits all
engine internals (``theta``, ``mastered_count``, total counts, the per-trial
score ``s`` and predicted success ``E``): the learner-facing UI sees only
counts, percentages, streaks, timing, and per-level completion.

Handlers are thin adapters over the *same* shared
:class:`~math_practice_backend.service.SessionService` used by the admin
``/v1/sessions`` API (resolved via the existing DI providers). Service-layer
exceptions propagate untouched and are mapped to status codes by the handlers
registered in :mod:`math_practice_backend.app`:

    * unknown session id   -> 404 (:class:`SessionNotFound`)
    * expired session      -> 410 (:class:`SessionExpired`)
    * no pending exercise  -> 409 (:class:`NoPendingExercise`)
    * run already complete  -> 409 (:class:`SessionComplete`)
    * unknown module id    -> 404 (:class:`ModuleNotFound`)
    * unknown mode         -> 422 (:class:`UnknownMode`)

A 409 on ``/next`` signals the client that the stop rule is already met and it
should navigate to the summary.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, status

from math_practice import MODULES

from . import mappers
from .auth import AuthIdentity
from .dependencies import (
    get_identity_service,
    get_optional_identity,
    get_required_identity,
    get_service,
    get_stats_service,
)
from .enums import Mode
from .errors import UnknownMode
from .identity_service import IdentityService
from .schemas import (
    AnswerIn,
    ClaimIn,
    ClaimOut,
    CreateStudentSessionIn,
    ExerciseOut,
    MeOut,
    ModeOut,
    ModuleOut,
    StudentAnswerOut,
    StudentSessionOut,
    StudentStatsOut,
    StudentSummaryOut,
)
from .service import SessionService, StatsService

router = APIRouter(prefix="/v1/play", tags=["play"])


#: Mode descriptors for the main screen, in display order. Kept here (not in the
#: engine) because a mode is a backend concept — a stop rule + headline metric.
_MODE_DESCRIPTORS: tuple[ModeOut, ...] = (
    ModeOut(
        id=Mode.FASTEST_20.value,
        label="Fastest 20",
        description="Answer 20 questions as fast as you can.",
    ),
    ModeOut(
        id=Mode.THREE_MINUTE.value,
        label="3 minutes",
        description="Solve as many as you can before time runs out.",
    ),
    ModeOut(
        id=Mode.ENDLESS.value,
        label="Endless",
        description="Keep practicing for as long as you like.",
    ),
)


def _parse_mode(mode: str) -> Mode:
    """Resolve a wire mode string to a :class:`Mode`, else raise.

    Args:
        mode: the mode value sent by the client.

    Returns:
        The matching :class:`Mode` enum member.

    Raises:
        UnknownMode: if ``mode`` is not a recognised practice mode.
    """
    try:
        return Mode(mode)
    except ValueError as exc:
        raise UnknownMode(mode) from exc


def _deadline_for(agg) -> datetime | None:
    """Return the run's wall-clock deadline, or ``None`` for an untimed run.

    The deadline is ``started_at + target_seconds`` and is known at creation, so
    a timed client can drive its countdown off the server-authoritative value.

    Args:
        agg: the session aggregate.

    Returns:
        The deadline (aware UTC) for a time-bound mode, else ``None``.
    """
    if agg.target_seconds is None:
        return None
    return agg.started_at + timedelta(seconds=agg.target_seconds)


@router.get(
    "/modules",
    response_model=list[ModuleOut],
)
async def list_modules() -> list[ModuleOut]:
    """List the practice modules for the main screen, in a stable order.

    Order is ``add_10, add_20, add_100, sub_10, sub_20, sub_100`` (the registry
    insertion order), so the addition and subtraction groups stay together.
    """
    return [mappers.module_to_out(spec) for spec in MODULES.values()]


@router.get(
    "/modes",
    response_model=list[ModeOut],
)
async def list_modes() -> list[ModeOut]:
    """List the selectable practice modes for the main screen."""
    return list(_MODE_DESCRIPTORS)


@router.post(
    "/sessions",
    response_model=StudentSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_play_session(
    body: CreateStudentSessionIn,
    service: SessionService = Depends(get_service),
    identity: AuthIdentity | None = Depends(get_optional_identity),
    identity_service: IdentityService = Depends(get_identity_service),
) -> StudentSessionOut:
    """Create a play session for a ``(module, mode)``, minting a learner if needed.

    When a valid ``Authorization: Bearer <token>`` is present the server resolves
    the *user's* learner and uses it, ignoring ``body.learner_id``. Otherwise the
    run is anonymous: ``body.learner_id`` is resumed (or a fresh learner minted).

    Returns the identity the client persists (``session_id`` + ``learner_id``),
    the chosen module/mode, the 24h expiry, and the mode's stop-rule parameters
    (including a server-authoritative ``deadline`` for the timed mode). No engine
    internals are exposed.
    """
    mode = _parse_mode(body.mode)
    if identity is not None:
        learner = identity_service.resolve_learner(identity)
        learner_id = learner.id
    else:
        learner_id = body.learner_id
    agg = service.create_session(
        learner_id=learner_id,
        module_id=body.module_id,
        mode=mode,
        overrides=None,
    )
    return StudentSessionOut(
        session_id=agg.id,
        learner_id=agg.learner_id,
        module_id=agg.module_id,
        mode=agg.mode.value,
        started_at=agg.started_at,
        expires_at=agg.expires_at,
        target_count=agg.target_count,
        target_seconds=agg.target_seconds,
        deadline=_deadline_for(agg),
    )


@router.get(
    "/me",
    response_model=MeOut,
)
async def play_me(
    identity: AuthIdentity = Depends(get_required_identity),
    identity_service: IdentityService = Depends(get_identity_service),
) -> MeOut:
    """Return the signed-in user's account learner id and email.

    Requires a valid ``Authorization: Bearer <token>`` (else ``401``). Resolves
    (creating on first sight) the user's single learner.
    """
    learner = identity_service.resolve_learner(identity)
    return MeOut(learner_id=learner.id, email=identity.email)


@router.post(
    "/claim",
    response_model=ClaimOut,
)
async def play_claim(
    body: ClaimIn,
    identity: AuthIdentity = Depends(get_required_identity),
    identity_service: IdentityService = Depends(get_identity_service),
) -> ClaimOut:
    """Fold an anonymous learner's progress into the signed-in user's learner.

    Requires a valid token (else ``401``). Adopts the anonymous learner if the
    user has none yet, else merges its per-module progress keeping the
    more-advanced state. Returns the user's learner id.
    """
    learner = identity_service.claim_anonymous(
        identity, body.anonymous_learner_id
    )
    return ClaimOut(learner_id=learner.id)


@router.post(
    "/sessions/{sid}/next",
    response_model=ExerciseOut,
)
async def play_next(
    sid: str,
    service: SessionService = Depends(get_service),
) -> ExerciseOut:
    """Draw the next exercise (or re-show the pending one on resume).

    A completed run (stop rule already met) raises :class:`SessionComplete`,
    surfaced as ``409`` to tell the client to go to the summary.
    """
    pending = service.get_next(sid)
    return mappers.pending_to_exercise_out(pending)


@router.post(
    "/sessions/{sid}/answers",
    response_model=StudentAnswerOut,
)
async def play_answer(
    sid: str,
    body: AnswerIn,
    service: SessionService = Depends(get_service),
    stats_service: StatsService = Depends(get_stats_service),
) -> StudentAnswerOut:
    """Grade an answer and return the freshly-recomputed surface metrics.

    Correctness plus the *post-answer* counts (questions done, module completion
    percentage, current correct streak), whether the run is now finished, and
    the mode's ``remaining`` payload (``seconds_left`` for the timed mode,
    ``questions_left`` for the count-bound mode) are returned. No engine
    internals leak.
    """
    outcome = service.submit_answer(sid, body.answer, body.elapsed_seconds)
    agg = service.get_session(sid)
    stats = stats_service.get_student_stats(agg)
    return StudentAnswerOut(
        correct=outcome.trial.correct,
        questions_done=stats.questions_done,
        module_completion_percent=stats.module_completion_percent,
        streak=stats.streak,
        finished=outcome.finished,
        seconds_left=outcome.remaining.get("seconds_left"),
        questions_left=outcome.remaining.get("questions_left"),
    )


@router.get(
    "/sessions/{sid}/summary",
    response_model=StudentSummaryOut,
)
async def play_summary(
    sid: str,
    service: SessionService = Depends(get_service),
    stats_service: StatsService = Depends(get_stats_service),
) -> StudentSummaryOut:
    """Return the run's headline metric, personal best, and per-level mastery."""
    agg = service.get_session(sid)
    summary = stats_service.get_summary(agg)
    return mappers.summary_to_out(summary)


@router.get(
    "/sessions/{sid}/stats",
    response_model=StudentStatsOut,
)
async def play_stats(
    sid: str,
    service: SessionService = Depends(get_service),
    stats_service: StatsService = Depends(get_stats_service),
) -> StudentStatsOut:
    """Return student-safe aggregate statistics (counts, timing, streak)."""
    agg = service.get_session(sid)
    stats = stats_service.get_student_stats(agg)
    return StudentStatsOut(
        questions_done=stats.questions_done,
        correct=stats.correct,
        accuracy=stats.accuracy,
        total_time_seconds=stats.total_time_seconds,
        avg_time_seconds=stats.avg_time_seconds,
        module_completion_percent=stats.module_completion_percent,
        streak=stats.streak,
    )
