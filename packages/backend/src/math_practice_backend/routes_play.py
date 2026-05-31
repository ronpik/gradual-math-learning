"""Student-safe HTTP routes (the ``/v1/play`` API).

This router exposes the *only* surface the static web client talks to. Every
response is a ``Student*`` schema that deliberately omits all engine internals
(``theta``, ``mastered_count``, ``total``, the per-trial score ``s`` and
predicted success ``E``): the learner-facing UI sees only counts, percentages,
streaks, and timing.

Handlers are thin adapters over the *same* shared
:class:`~math_practice_backend.service.SessionService` used by the admin
``/v1/sessions`` API (resolved via the existing DI providers). Service-layer
exceptions propagate untouched and are mapped to status codes by the handlers
registered in :mod:`math_practice_backend.app`:

    * unknown session id   -> 404 (:class:`SessionNotFound`)
    * expired session      -> 410 (:class:`SessionExpired`)
    * no pending exercise  -> 409 (:class:`NoPendingExercise`)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from . import mappers
from .dependencies import get_service
from .schemas import (
    AnswerIn,
    CreateSessionIn,
    ExerciseOut,
    StudentAnswerOut,
    StudentSessionOut,
    StudentStatsOut,
)
from .service import SessionService

router = APIRouter(prefix="/v1/play", tags=["play"])


@router.post(
    "/sessions",
    response_model=StudentSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_play_session(
    body: CreateSessionIn | None = None,
    service: SessionService = Depends(get_service),
) -> StudentSessionOut:
    """Create a new practice session, returning only the id + expiry."""
    overrides = (
        body.config.to_overrides()
        if body is not None and body.config is not None
        else None
    )
    agg = service.create_session(overrides)
    return StudentSessionOut(session_id=agg.id, expires_at=agg.expires_at)


@router.post(
    "/sessions/{sid}/next",
    response_model=ExerciseOut,
)
async def play_next(
    sid: str,
    service: SessionService = Depends(get_service),
) -> ExerciseOut:
    """Draw the next exercise (or re-show the pending one on resume)."""
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
) -> StudentAnswerOut:
    """Grade an answer and return the freshly-recomputed surface metrics.

    Correctness plus the *post-answer* counts (questions done, module completion
    percentage, current correct streak) are returned. No engine internals leak.
    """
    outcome = service.submit_answer(sid, body.answer, body.elapsed_seconds)
    stats = service.get_student_stats(sid)
    return StudentAnswerOut(
        correct=outcome.trial.correct,
        questions_done=stats.questions_done,
        module_completion_percent=stats.module_completion_percent,
        streak=stats.streak,
    )


@router.get(
    "/sessions/{sid}/stats",
    response_model=StudentStatsOut,
)
async def play_stats(
    sid: str,
    service: SessionService = Depends(get_service),
) -> StudentStatsOut:
    """Return student-safe aggregate statistics (counts, timing, streak)."""
    stats = service.get_student_stats(sid)
    return StudentStatsOut(
        questions_done=stats.questions_done,
        correct=stats.correct,
        accuracy=stats.accuracy,
        total_time_seconds=stats.total_time_seconds,
        avg_time_seconds=stats.avg_time_seconds,
        module_completion_percent=stats.module_completion_percent,
        streak=stats.streak,
    )
