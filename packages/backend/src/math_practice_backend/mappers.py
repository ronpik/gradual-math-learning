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

from math_practice import EngineState, ExerciseMastery, ModuleSpec

from .domain import PendingExercise, SessionAggregate, SessionExercise, TrialRecord
from .schemas import (
    ExerciseOut,
    LevelProgressOut,
    MasteryOut,
    ModuleOut,
    ProgressOut,
    SessionExerciseOut,
    SessionOut,
    StatsOut,
    StudentSummaryOut,
    TrialOut,
)
from .service import LevelProgress, SummaryResult


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
    """Map a :class:`PendingExercise` dataclass to an :class:`ExerciseOut`.

    Carries the pending exercise's own ``op`` (``"+"`` or ``"-"``) so the client
    renders the correct operator instead of assuming addition.
    """
    return ExerciseOut(
        a=pending.a,
        b=pending.b,
        op=pending.op,
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
        module_id=agg.module_id,
        mode=agg.mode.value,
        status=agg.status.value,
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


def session_exercise_to_out(exercise: SessionExercise) -> SessionExerciseOut:
    """Map a :class:`SessionExercise` audit row to a :class:`SessionExerciseOut`."""
    return SessionExerciseOut(
        seq=exercise.seq,
        a=exercise.a,
        b=exercise.b,
        op=exercise.op,
        level=exercise.level,
        given_answer=exercise.given_answer,
        correct=exercise.correct,
        elapsed=exercise.elapsed,
        created_at=exercise.created_at,
    )


def module_to_out(spec: ModuleSpec) -> ModuleOut:
    """Map an engine :class:`~math_practice.ModuleSpec` to a :class:`ModuleOut`.

    Surfaces only the student-safe descriptor fields — id, operator, range
    bound, label, and the module's applicable structural levels — never the
    config knobs or scorer.
    """
    return ModuleOut(
        id=spec.id,
        op=spec.op,
        range_bound=spec.range_bound,
        label=spec.label,
        levels=list(spec.applicable_levels),
    )


def level_progress_to_out(level: LevelProgress) -> LevelProgressOut:
    """Map a service :class:`LevelProgress` to a :class:`LevelProgressOut`."""
    return LevelProgressOut(
        level=level.level,
        mastered=level.mastered,
        total=level.total,
    )


def summary_to_out(summary: SummaryResult) -> StudentSummaryOut:
    """Map a service :class:`SummaryResult` to a :class:`StudentSummaryOut`.

    The mode's personal best is a count (int) for the 3-minute mode and a
    duration (float) for Fastest-20; it is widened to ``float`` (or left
    ``None``) on the student surface so the shape is uniform.

    Args:
        summary: the end-of-run summary projection.

    Returns:
        The student-safe summary payload — headline, personal best, and
        per-level mastery — with no engine internals.
    """
    best = summary.best
    return StudentSummaryOut(
        module_id=summary.module_id,
        label=summary.label,
        mode=summary.mode.value,
        status=summary.status.value,
        questions_done=summary.questions_done,
        correct=summary.correct_count,
        accuracy=summary.accuracy,
        total_time_seconds=summary.total_time,
        avg_time_seconds=summary.avg_time,
        headline=summary.headline,
        personal_best=(float(best) if best is not None else None),
        is_new_best=summary.is_new_best,
        levels=[level_progress_to_out(lp) for lp in summary.level_progress],
    )
