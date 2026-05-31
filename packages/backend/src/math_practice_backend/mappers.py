"""Pure mappers from internal dataclasses to HTTP-edge Pydantic schemas.

Every function here is side-effect-free and free of any ORM or DB concern: it
takes the backend's domain dataclasses (:mod:`math_practice_backend.domain`)
and/or the engine's :class:`~math_practice.EngineState` /
:class:`~math_practice.ExerciseMastery` and produces the matching
:mod:`math_practice_backend.schemas` model.

The inverse direction (HTTP request -> dataclass/override dict) is intentionally
trivial and handled inline by the schemas themselves
(:meth:`~math_practice_backend.schemas.ConfigOverrides.to_overrides`).
"""

from __future__ import annotations

from math_practice import EngineState, ExerciseMastery

from .domain import PendingExercise, SessionAggregate, TrialRecord
from .schemas import (
    ExerciseOut,
    MasteryOut,
    ProgressOut,
    SessionOut,
    StatsOut,
    TrialOut,
)

#: Operator label surfaced to clients (the curriculum is addition-only, v1).
OP_ADD = "+"


def progress_to_out(
    engine_state: EngineState, mastered_count: int, total: int
) -> ProgressOut:
    """Build a :class:`ProgressOut` from engine state plus mastery counts.

    Args:
        engine_state:   the session's restorable engine snapshot (for ``theta``).
        mastered_count: number of mastered exercises.
        total:          total number of curriculum exercises.

    Returns:
        The progress projection; ``all_mastered`` is ``True`` when
        ``mastered_count == total`` (and ``total > 0``).
    """
    return ProgressOut(
        theta=engine_state.theta,
        mastered_count=mastered_count,
        total=total,
        all_mastered=total > 0 and mastered_count >= total,
    )


def pending_to_exercise_out(pending: PendingExercise) -> ExerciseOut:
    """Map a :class:`PendingExercise` dataclass to an :class:`ExerciseOut`."""
    return ExerciseOut(
        a=pending.a,
        b=pending.b,
        op=OP_ADD,
        issued_at=pending.issued_at,
    )


def mastery_to_out(mastery: ExerciseMastery) -> MasteryOut:
    """Map an :class:`~math_practice.ExerciseMastery` to a :class:`MasteryOut`."""
    return MasteryOut(
        streak=mastery.streak,
        faults=mastery.faults,
        mastered=mastery.mastered,
    )


def session_to_out(
    agg: SessionAggregate, mastered_count: int, total: int
) -> SessionOut:
    """Map a :class:`SessionAggregate` to a :class:`SessionOut`.

    Args:
        agg:            the full session aggregate.
        mastered_count: number of mastered exercises.
        total:          total number of curriculum exercises.

    Returns:
        The session view, including the pending exercise (if any) and progress.
    """
    return SessionOut(
        session_id=agg.id,
        created_at=agg.created_at,
        last_activity_at=agg.last_activity_at,
        expires_at=agg.expires_at,
        progress=progress_to_out(agg.engine_state, mastered_count, total),
        pending=(
            pending_to_exercise_out(agg.pending) if agg.pending is not None else None
        ),
    )


def trial_to_out(
    trial: TrialRecord, mastery: ExerciseMastery, progress: ProgressOut
) -> TrialOut:
    """Map a graded :class:`TrialRecord` to a :class:`TrialOut`.

    Args:
        trial:    the persisted trial record.
        mastery:  the post-trial mastery state for the trial's exercise.
        progress: the session progress after applying the trial.

    Returns:
        The full trial result projection.
    """
    return TrialOut(
        seq=trial.seq,
        a=trial.a,
        b=trial.b,
        correct=trial.correct,
        response_time=trial.response_time,
        s=trial.s,
        E=trial.E,
        theta_before=trial.theta_before,
        theta_after=trial.theta_after,
        mastery=mastery_to_out(mastery),
        progress=progress,
    )


def build_stats_out(
    progress: ProgressOut,
    trials: int,
    correct: int,
    recent: list[TrialOut],
) -> StatsOut:
    """Assemble a :class:`StatsOut` from precomputed parts.

    Args:
        progress: the current session progress.
        trials:   total number of recorded trials.
        correct:  number of correct trials.
        recent:   already-mapped recent trial projections (newest-first).

    Returns:
        The aggregate stats payload; ``accuracy`` is ``correct / trials`` (or
        ``0.0`` when there are no trials).
    """
    accuracy = (correct / trials) if trials > 0 else 0.0
    return StatsOut(
        progress=progress,
        trials=trials,
        correct=correct,
        accuracy=accuracy,
        recent=recent,
    )
