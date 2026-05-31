"""HTTP routes for the math-practice backend.

Defines the versioned ``/v1`` session API plus the unversioned ``/health``
probe. Each handler is a thin adapter: it resolves the shared
:class:`~math_practice_backend.service.SessionService` via dependency injection,
delegates to a single service method, and maps the returned dataclasses to the
Pydantic response schemas in :mod:`math_practice_backend.mappers`.

Service-layer exceptions (not-found / expired / no-pending / invalid-config)
propagate untouched; the exception handlers registered in
:mod:`math_practice_backend.app` translate them to status codes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from math_practice import ExerciseMastery

from . import mappers
from .dependencies import get_repository, get_service
from .domain import SessionAggregate, TrialRecord
from .repositories import SessionRepository
from .schemas import (
    AnswerIn,
    CreateSessionIn,
    ExerciseOut,
    HealthOut,
    ProgressOut,
    SessionOut,
    StatsOut,
    TrialOut,
)
from .service import Progress, SessionService


def _progress_out(progress: Progress) -> ProgressOut:
    """Map a service :class:`Progress` projection to a :class:`ProgressOut`."""
    return ProgressOut(
        theta=progress.theta,
        mastered_count=progress.mastered_count,
        total=progress.total,
        all_mastered=progress.all_mastered,
    )

router = APIRouter()


@router.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    """Liveness probe returning a static OK payload."""
    return HealthOut(status="ok")


def _session_out(agg: SessionAggregate, progress: Progress) -> SessionOut:
    """Map an aggregate + progress projection to a :class:`SessionOut`."""
    return mappers.session_to_out(
        agg, mastered_count=progress.mastered_count, total=progress.total
    )


@router.post(
    "/v1/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
)
async def create_session(
    body: CreateSessionIn | None = None,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    """Create a new practice session (no pending exercise yet)."""
    overrides = (
        body.config.to_overrides()
        if body is not None and body.config is not None
        else None
    )
    agg = service.create_session(overrides)
    return _session_out(agg, SessionService.progress(agg))


@router.get(
    "/v1/sessions/{sid}",
    response_model=SessionOut,
    tags=["sessions"],
)
async def get_session(
    sid: str,
    service: SessionService = Depends(get_service),
) -> SessionOut:
    """Fetch a session, sliding its activity window."""
    agg = service.get_session(sid)
    return _session_out(agg, SessionService.progress(agg))


@router.delete(
    "/v1/sessions/{sid}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["sessions"],
)
async def delete_session(
    sid: str,
    service: SessionService = Depends(get_service),
    repo: SessionRepository = Depends(get_repository),
) -> None:
    """Delete a session.

    Validates existence/expiry first (so unknown ids yield 404 and expired ids
    410), then removes the session and its cascade.
    """
    service.get_session(sid)
    repo.delete(sid)


@router.post(
    "/v1/sessions/{sid}/next",
    response_model=ExerciseOut,
    tags=["sessions"],
)
async def get_next(
    sid: str,
    service: SessionService = Depends(get_service),
) -> ExerciseOut:
    """Draw the next exercise (or re-show the pending one)."""
    pending = service.get_next(sid)
    return mappers.pending_to_exercise_out(pending)


@router.post(
    "/v1/sessions/{sid}/answers",
    response_model=TrialOut,
    tags=["sessions"],
)
async def submit_answer(
    sid: str,
    body: AnswerIn,
    service: SessionService = Depends(get_service),
) -> TrialOut:
    """Grade a submitted answer and return the trial result."""
    outcome = service.submit_answer(sid, body.answer, body.elapsed_seconds)
    progress = _progress_out(outcome.progress)
    return mappers.trial_to_out(outcome.trial, outcome.mastery, progress)


@router.get(
    "/v1/sessions/{sid}/stats",
    response_model=StatsOut,
    tags=["sessions"],
)
async def get_stats(
    sid: str,
    service: SessionService = Depends(get_service),
) -> StatsOut:
    """Return aggregate session statistics with a recent-trials tail."""
    result = service.get_stats(sid)
    progress = _progress_out(result.progress)
    recent = [
        mappers.trial_to_out(
            trial,
            _mastery_for(result.aggregate, trial),
            progress,
        )
        for trial in result.recent
    ]
    return mappers.build_stats_out(
        progress=progress,
        trials=result.trials,
        correct=result.correct,
        recent=recent,
    )


def _mastery_for(
    agg: SessionAggregate, trial: TrialRecord
) -> ExerciseMastery:
    """Resolve current mastery for a trial's exercise from the aggregate state.

    Recent trials in the stats tail report the *current* mastery for their
    ``(a, b)`` item (historical per-trial mastery is not persisted). Falls back
    to a zeroed mastery if the item is not present in the engine state.
    """
    for m in agg.engine_state.mastery:
        if m.a == trial.a and m.b == trial.b:
            return m
    return ExerciseMastery(
        a=trial.a, b=trial.b, streak=0, faults=0, mastered=False
    )
