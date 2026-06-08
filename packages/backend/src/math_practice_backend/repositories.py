"""Repository layer for practice sessions and learners.

Defines two abstract persistence boundaries — :class:`SessionRepository` (the
ephemeral 24h session aggregate plus its trial and audit logs) and
:class:`LearnerRepository` (the permanent learner identity and its resumable
per-(learner, module) progress) — each with a SQLAlchemy 2.0 implementation. The
repositories are the *only* place ORM rows exist: every public method accepts and
returns the domain dataclasses
(:class:`~math_practice_backend.domain.SessionAggregate`,
:class:`~math_practice_backend.domain.SessionExercise`,
:class:`~math_practice_backend.domain.TrialRecord`,
:class:`~math_practice_backend.domain.Learner`,
:class:`~math_practice_backend.domain.ModuleProgress`) and the engine value
objects (:class:`~math_practice.EngineState`,
:class:`~math_practice.ExerciseMastery`,
:class:`~math_practice.EngineConfig`). ORM objects never leak out.

The repositories own serialisation: :class:`EngineConfig` maps to/from a JSON
column via :func:`dataclasses.asdict` / ``EngineConfig(**d)``; session mastery maps
to/from ``session_mastery`` rows; module-progress mastery maps to/from a JSON blob
of ``{a, b, streak, faults, mastered}`` dicts; and last-shown/pending exercises map
to/from nullable columns. The split keeps each interface cohesive and the two
distinct lifetimes (permanent learner vs ephemeral session) explicit.
"""

from __future__ import annotations

import abc
import dataclasses
from datetime import datetime, timezone
from typing import Any
import uuid
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from math_practice import EngineConfig, EngineState, ExerciseMastery

from .domain import (
    Learner,
    ModuleProgress,
    PendingExercise,
    SessionAggregate,
    SessionExercise,
    TrialRecord,
    User,
)
from .enums import Mode, SessionStatus
from .models import (
    LearnerModuleProgressRow,
    LearnerRow,
    MasteryRow,
    SessionExerciseRow,
    SessionRow,
    TrialRow,
    UserRow,
)


def _as_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    SQLite stores naive datetimes; values read back are reattached to UTC, and
    aware values from other backends are converted to UTC.

    Args:
        value: a naive (assumed-UTC) or aware datetime.

    Returns:
        The equivalent timezone-aware UTC datetime.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SessionRepository(abc.ABC):
    """Persistence boundary for practice sessions and their trial log.

    All methods exchange domain dataclasses only; implementations must not
    expose ORM rows to callers.
    """

    @abc.abstractmethod
    def create(self, session: SessionAggregate) -> None:
        """Insert a brand-new session aggregate (with its mastery rows)."""

    @abc.abstractmethod
    def get(self, session_id: str) -> SessionAggregate | None:
        """Load a session aggregate by id, or ``None`` if it does not exist."""

    @abc.abstractmethod
    def save(self, session: SessionAggregate) -> None:
        """Upsert session metadata + engine state + mastery + pending."""

    @abc.abstractmethod
    def add_trial(self, session_id: str, trial: TrialRecord) -> None:
        """Append a graded trial to the session's trial log."""

    @abc.abstractmethod
    def add_session_exercise(
        self, session_id: str, exercise: SessionExercise
    ) -> None:
        """Append an answered question to the session's clean audit log."""

    @abc.abstractmethod
    def list_session_exercises(
        self, session_id: str, limit: int | None = None
    ) -> list[SessionExercise]:
        """Return the session's audit rows ordered by ``seq`` (optionally capped)."""

    @abc.abstractmethod
    def list_trials(
        self, session_id: str, limit: int | None = None
    ) -> list[TrialRecord]:
        """Return the session's trials, newest first (optionally capped)."""

    @abc.abstractmethod
    def count_trials(self, session_id: str) -> int:
        """Return the number of trials recorded for the session."""

    @abc.abstractmethod
    def correct_count(self, session_id: str) -> int:
        """Return the number of correct trials recorded for the session."""

    @abc.abstractmethod
    def sum_response_time(self, session_id: str) -> float:
        """Return the summed response time over the session's trials (0 if none)."""

    @abc.abstractmethod
    def best_result(
        self, learner_id: str, module_id: str, mode: Mode
    ) -> float | int | None:
        """Return the personal best over the learner's *completed* sessions.

        Scoped to ``(learner_id, module_id, mode)`` and ``COMPLETED`` sessions:
        for :attr:`Mode.FASTEST_20` the minimum ``total_time`` among sessions with
        at least 20 answered; for :attr:`Mode.THREE_MINUTE` the maximum
        ``questions_done``; for :attr:`Mode.ENDLESS` always ``None`` (no best).
        Returns ``None`` when no qualifying session exists.
        """

    @abc.abstractmethod
    def list_sessions_for_learner(
        self, learner_id: str, limit: int | None = None
    ) -> list[SessionAggregate]:
        """Return the learner's sessions newest-first (optionally capped)."""

    @abc.abstractmethod
    def delete(self, session_id: str) -> None:
        """Delete a session and (by cascade) its mastery rows and trials."""

    @abc.abstractmethod
    def purge_expired(self, now: datetime) -> int:
        """Delete sessions with ``expires_at <= now``; return the count deleted."""


class SqlAlchemySessionRepository(SessionRepository):
    """SQLAlchemy 2.0 implementation backed by a :class:`sessionmaker`.

    A fresh :class:`~sqlalchemy.orm.Session` is opened and committed/rolled back
    per public call, keeping the repository stateless and thread-safe for the
    shared in-memory engine.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        """Bind the repository to a session factory.

        Args:
            session_factory: a configured :class:`~sqlalchemy.orm.sessionmaker`
                bound to the application engine.
        """
        self._session_factory = session_factory

    # ----- (de)serialisation helpers ---------------------------------------

    @staticmethod
    def _engine_state_to_row(row: SessionRow, agg: SessionAggregate) -> None:
        """Write an aggregate's metadata + engine state onto an ORM row."""
        state = agg.engine_state
        row.learner_id = agg.learner_id
        row.module_id = agg.module_id
        row.mode = agg.mode
        row.status = agg.status
        row.created_at = agg.created_at
        row.started_at = agg.started_at
        row.ended_at = agg.ended_at
        row.last_activity_at = agg.last_activity_at
        row.expires_at = agg.expires_at
        row.target_count = agg.target_count
        row.target_seconds = agg.target_seconds
        row.theta = state.theta
        row.config = dataclasses.asdict(state.config)
        if state.last_shown is None:
            row.last_shown_a = None
            row.last_shown_b = None
        else:
            row.last_shown_a, row.last_shown_b = state.last_shown
        if agg.pending is None:
            row.pending_a = None
            row.pending_b = None
            row.pending_issued_at = None
        else:
            row.pending_a = agg.pending.a
            row.pending_b = agg.pending.b
            row.pending_issued_at = agg.pending.issued_at
        row.trial_seq = agg.trial_seq
        row.questions_done = agg.questions_done
        row.correct_count = agg.correct_count
        row.total_time = agg.total_time

    @staticmethod
    def _mastery_rows(agg: SessionAggregate) -> list[MasteryRow]:
        """Build fresh mastery ORM rows from the aggregate's engine state."""
        return [
            MasteryRow(
                session_id=agg.id,
                a=m.a,
                b=m.b,
                streak=m.streak,
                faults=m.faults,
                mastered=m.mastered,
            )
            for m in agg.engine_state.mastery
        ]

    @staticmethod
    def _row_to_aggregate(
        row: SessionRow, mastery_rows: list[MasteryRow]
    ) -> SessionAggregate:
        """Build a :class:`SessionAggregate` from ORM rows (no ORM leakage)."""
        config = EngineConfig(**row.config)
        mastery = [
            ExerciseMastery(
                a=m.a,
                b=m.b,
                streak=m.streak,
                faults=m.faults,
                mastered=m.mastered,
            )
            for m in mastery_rows
        ]
        last_shown: tuple[int, int] | None
        if row.last_shown_a is None or row.last_shown_b is None:
            last_shown = None
        else:
            last_shown = (row.last_shown_a, row.last_shown_b)
        engine_state = EngineState(
            theta=row.theta,
            config=config,
            mastery=mastery,
            last_shown=last_shown,
        )
        pending: PendingExercise | None = None
        if (
            row.pending_a is not None
            and row.pending_b is not None
            and row.pending_issued_at is not None
        ):
            pending = PendingExercise(
                a=row.pending_a,
                b=row.pending_b,
                issued_at=_as_utc(row.pending_issued_at),
                op=config.op,
            )
        return SessionAggregate(
            id=row.id,
            learner_id=row.learner_id,
            module_id=row.module_id,
            mode=row.mode,
            status=row.status,
            created_at=_as_utc(row.created_at),
            started_at=_as_utc(row.started_at),
            ended_at=_as_utc(row.ended_at) if row.ended_at is not None else None,
            last_activity_at=_as_utc(row.last_activity_at),
            expires_at=_as_utc(row.expires_at),
            target_count=row.target_count,
            target_seconds=row.target_seconds,
            engine_state=engine_state,
            pending=pending,
            trial_seq=row.trial_seq,
            questions_done=row.questions_done,
            correct_count=row.correct_count,
            total_time=row.total_time,
        )

    @staticmethod
    def _trial_row_to_record(row: TrialRow) -> TrialRecord:
        """Map a ``trials`` ORM row to a :class:`TrialRecord`."""
        return TrialRecord(
            seq=row.seq,
            a=row.a,
            b=row.b,
            correct=row.correct,
            response_time=row.response_time,
            s=row.s,
            E=row.e,
            theta_before=row.theta_before,
            theta_after=row.theta_after,
            created_at=_as_utc(row.created_at),
        )

    @staticmethod
    def _session_exercise_row_to_record(
        row: SessionExerciseRow,
    ) -> SessionExercise:
        """Map a ``session_exercises`` ORM row to a :class:`SessionExercise`."""
        return SessionExercise(
            seq=row.seq,
            a=row.a,
            b=row.b,
            op=row.op,
            level=row.level,
            given_answer=row.given_answer,
            correct=row.correct,
            elapsed=row.elapsed,
            created_at=_as_utc(row.created_at),
        )

    # ----- repository API ---------------------------------------------------

    def create(self, session: SessionAggregate) -> None:
        """Insert a new session row plus its initial mastery rows."""
        with self._session_factory() as db:
            row = SessionRow(id=session.id)
            self._engine_state_to_row(row, session)
            row.mastery = self._mastery_rows(session)
            db.add(row)
            db.commit()

    def get(self, session_id: str) -> SessionAggregate | None:
        """Load a session aggregate by id, or ``None`` if absent."""
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return None
            mastery_rows = list(
                db.scalars(
                    select(MasteryRow).where(MasteryRow.session_id == session_id)
                )
            )
            return self._row_to_aggregate(row, mastery_rows)

    def save(self, session: SessionAggregate) -> None:
        """Upsert metadata + engine state, replace mastery rows, persist pending.

        The session row is updated in place; all mastery rows are deleted and
        re-inserted from the current engine state to keep them authoritative.
        """
        with self._session_factory() as db:
            row = db.get(SessionRow, session.id)
            if row is None:
                row = SessionRow(id=session.id)
                db.add(row)
            self._engine_state_to_row(row, session)

            db.execute(
                delete(MasteryRow).where(MasteryRow.session_id == session.id)
            )
            db.flush()
            db.add_all(self._mastery_rows(session))
            db.commit()

    def add_trial(self, session_id: str, trial: TrialRecord) -> None:
        """Append a graded trial to the session's append-only log."""
        with self._session_factory() as db:
            db.add(
                TrialRow(
                    session_id=session_id,
                    seq=trial.seq,
                    a=trial.a,
                    b=trial.b,
                    correct=trial.correct,
                    response_time=trial.response_time,
                    s=trial.s,
                    e=trial.E,
                    theta_before=trial.theta_before,
                    theta_after=trial.theta_after,
                    created_at=trial.created_at,
                )
            )
            db.commit()

    def add_session_exercise(
        self, session_id: str, exercise: SessionExercise
    ) -> None:
        """Append an answered question to the append-only audit log."""
        with self._session_factory() as db:
            db.add(
                SessionExerciseRow(
                    session_id=session_id,
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
            )
            db.commit()

    def list_session_exercises(
        self, session_id: str, limit: int | None = None
    ) -> list[SessionExercise]:
        """Return the session's audit rows ordered by ``seq`` (optionally capped)."""
        with self._session_factory() as db:
            stmt = (
                select(SessionExerciseRow)
                .where(SessionExerciseRow.session_id == session_id)
                .order_by(SessionExerciseRow.seq.asc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = db.scalars(stmt)
            return [self._session_exercise_row_to_record(r) for r in rows]

    def list_trials(
        self, session_id: str, limit: int | None = None
    ) -> list[TrialRecord]:
        """Return the session's trials newest-first (optionally capped)."""
        with self._session_factory() as db:
            stmt = (
                select(TrialRow)
                .where(TrialRow.session_id == session_id)
                .order_by(TrialRow.seq.desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = db.scalars(stmt)
            return [self._trial_row_to_record(r) for r in rows]

    def count_trials(self, session_id: str) -> int:
        """Return the number of trials recorded for the session."""
        with self._session_factory() as db:
            return (
                db.scalar(
                    select(func.count())
                    .select_from(TrialRow)
                    .where(TrialRow.session_id == session_id)
                )
                or 0
            )

    def correct_count(self, session_id: str) -> int:
        """Return the number of correct trials recorded for the session."""
        with self._session_factory() as db:
            return (
                db.scalar(
                    select(func.count())
                    .select_from(TrialRow)
                    .where(TrialRow.session_id == session_id)
                    .where(TrialRow.correct.is_(True))
                )
                or 0
            )

    def sum_response_time(self, session_id: str) -> float:
        """Return the summed ``response_time`` over the session's trials.

        Computed with a SQL ``SUM``; yields ``0.0`` when the session has no
        recorded trials.
        """
        with self._session_factory() as db:
            total = db.scalar(
                select(func.sum(TrialRow.response_time)).where(
                    TrialRow.session_id == session_id
                )
            )
            return float(total) if total is not None else 0.0

    def best_result(
        self, learner_id: str, module_id: str, mode: Mode
    ) -> float | int | None:
        """Return the personal best over the learner's *completed* sessions.

        Scoped to ``(learner_id, module_id, mode)`` and
        :attr:`SessionStatus.COMPLETED`. :attr:`Mode.FASTEST_20` returns the
        minimum ``total_time`` among sessions with ``questions_done >= 20``;
        :attr:`Mode.THREE_MINUTE` returns the maximum ``questions_done``;
        :attr:`Mode.ENDLESS` has no best and returns ``None``. ``None`` is also
        returned when no qualifying session exists.
        """
        if mode is Mode.ENDLESS:
            return None
        with self._session_factory() as db:
            base = (
                select(SessionRow)
                .where(SessionRow.learner_id == learner_id)
                .where(SessionRow.module_id == module_id)
                .where(SessionRow.mode == mode)
                .where(SessionRow.status == SessionStatus.COMPLETED)
            )
            if mode is Mode.FASTEST_20:
                total = db.scalar(
                    base.with_only_columns(func.min(SessionRow.total_time)).where(
                        SessionRow.questions_done >= 20
                    )
                )
                return float(total) if total is not None else None
            # Mode.THREE_MINUTE
            best = db.scalar(
                base.with_only_columns(func.max(SessionRow.questions_done))
            )
            return int(best) if best is not None else None

    def list_sessions_for_learner(
        self, learner_id: str, limit: int | None = None
    ) -> list[SessionAggregate]:
        """Return the learner's sessions newest-first (optionally capped)."""
        with self._session_factory() as db:
            stmt = (
                select(SessionRow)
                .where(SessionRow.learner_id == learner_id)
                .order_by(SessionRow.created_at.desc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(db.scalars(stmt))
            aggregates: list[SessionAggregate] = []
            for row in rows:
                mastery_rows = list(
                    db.scalars(
                        select(MasteryRow).where(MasteryRow.session_id == row.id)
                    )
                )
                aggregates.append(self._row_to_aggregate(row, mastery_rows))
            return aggregates

    def delete(self, session_id: str) -> None:
        """Delete a session and cascade-delete its mastery rows and trials."""
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                db.delete(row)
                db.commit()

    def purge_expired(self, now: datetime) -> int:
        """Delete sessions with ``expires_at <= now``; return the count deleted.

        Expired sessions' mastery rows and trials are removed by the
        ``ON DELETE CASCADE`` foreign keys / ORM cascade.
        """
        cutoff = _as_utc(now)
        with self._session_factory() as db:
            expired_ids = list(
                db.scalars(
                    select(SessionRow.id).where(SessionRow.expires_at <= cutoff)
                )
            )
            if not expired_ids:
                return 0
            for sid in expired_ids:
                row = db.get(SessionRow, sid)
                if row is not None:
                    db.delete(row)
            db.commit()
            return len(expired_ids)


class LearnerRepository(abc.ABC):
    """Persistence boundary for permanent learners and their module progress.

    Split from :class:`SessionRepository` because learners and their resumable
    per-(learner, module) progress are a different aggregate with a different
    lifetime (permanent vs the session's 24h sliding expiry). All methods
    exchange domain dataclasses
    (:class:`~math_practice_backend.domain.Learner`,
    :class:`~math_practice_backend.domain.ModuleProgress`) and engine value
    objects only; implementations must not expose ORM rows to callers.
    """

    @abc.abstractmethod
    def get_or_create(self, learner_id: str | None, now: datetime) -> Learner:
        """Return an existing learner, or create one stamped at ``now``.

        When ``learner_id`` names an existing learner it is returned unchanged.
        Otherwise a new learner is created — minting a fresh uuid4 hex id when
        ``learner_id`` is ``None``, else adopting the provided id — with
        ``created_at`` taken from the caller's clock (``now``).
        """

    @abc.abstractmethod
    def get(self, learner_id: str) -> Learner | None:
        """Load a learner by id, or ``None`` if it does not exist."""

    @abc.abstractmethod
    def get_progress(
        self, learner_id: str, module_id: str
    ) -> ModuleProgress | None:
        """Load the learner's progress on ``module_id``, or ``None`` if absent."""

    @abc.abstractmethod
    def save_progress(self, progress: ModuleProgress) -> None:
        """Upsert the learner's per-module progress (θ + mastery)."""

    @abc.abstractmethod
    def list_progress_modules(self, learner_id: str) -> list[str]:
        """Return the module ids the learner has any progress on (may be empty)."""

    @abc.abstractmethod
    def link_learner_to_user(self, learner_id: str, user_id: str) -> None:
        """Set ``learners.user_id`` for an existing learner.

        Adopts a previously-anonymous learner under an authenticated user. A
        no-op if the learner does not exist.
        """

    @abc.abstractmethod
    def list_learners_for_user(self, user_id: str) -> list[Learner]:
        """Return all learners owned by ``user_id`` (empty if none)."""

    @abc.abstractmethod
    def create_learner_for_user(
        self, user_id: str, now: datetime
    ) -> Learner:
        """Mint a new learner already owned by ``user_id`` (atomic create+link).

        Used when an authenticated user has no learner yet: a fresh uuid4-hex
        learner is created with ``user_id`` set, stamped at ``now``.
        """


class SqlAlchemyLearnerRepository(LearnerRepository):
    """SQLAlchemy 2.0 implementation backed by a :class:`sessionmaker`.

    A fresh :class:`~sqlalchemy.orm.Session` is opened and committed/rolled back
    per public call, keeping the repository stateless and thread-safe for the
    shared in-memory engine.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        """Bind the repository to a session factory.

        Args:
            session_factory: a configured :class:`~sqlalchemy.orm.sessionmaker`
                bound to the application engine.
        """
        self._session_factory = session_factory

    # ----- (de)serialisation helpers ---------------------------------------

    @staticmethod
    def _mastery_to_json(
        mastery: list[ExerciseMastery],
    ) -> list[dict[str, Any]]:
        """Serialise mastery value objects to ``{a, b, streak, faults, mastered}``."""
        return [
            {
                "a": m.a,
                "b": m.b,
                "streak": m.streak,
                "faults": m.faults,
                "mastered": m.mastered,
            }
            for m in mastery
        ]

    @staticmethod
    def _mastery_from_json(
        blob: list[dict[str, Any]],
    ) -> list[ExerciseMastery]:
        """Deserialise a mastery JSON blob back to engine value objects."""
        return [
            ExerciseMastery(
                a=d["a"],
                b=d["b"],
                streak=d["streak"],
                faults=d["faults"],
                mastered=d["mastered"],
            )
            for d in blob
        ]

    @staticmethod
    def _learner_row_to_domain(row: LearnerRow) -> Learner:
        """Map a ``learners`` ORM row to a :class:`Learner`."""
        return Learner(
            id=row.id,
            created_at=_as_utc(row.created_at),
            user_id=row.user_id,
        )

    @classmethod
    def _progress_row_to_domain(
        cls, row: LearnerModuleProgressRow
    ) -> ModuleProgress:
        """Map a ``learner_module_progress`` ORM row to a :class:`ModuleProgress`."""
        return ModuleProgress(
            learner_id=row.learner_id,
            module_id=row.module_id,
            theta=row.theta,
            mastery=cls._mastery_from_json(row.mastery_json),
            updated_at=_as_utc(row.updated_at),
        )

    # ----- repository API ---------------------------------------------------

    def get_or_create(self, learner_id: str | None, now: datetime) -> Learner:
        """Return an existing learner, or create one stamped at ``now``."""
        created_at = _as_utc(now)
        # A client may supply a non-UUID learner_id (e.g. a stale or hand-rolled
        # value in an anonymous create body). With a native Uuid column a lookup
        # on such a value raises, so treat anything that is not a valid UUID as a
        # request to mint a fresh learner rather than 500-ing.
        valid_id: str | None = None
        if learner_id is not None:
            try:
                uuid.UUID(learner_id)
                valid_id = learner_id
            except (ValueError, AttributeError, TypeError):
                valid_id = None
        with self._session_factory() as db:
            if valid_id is not None:
                row = db.get(LearnerRow, valid_id)
                if row is not None:
                    return self._learner_row_to_domain(row)
            new_id = valid_id if valid_id is not None else str(uuid4())
            row = LearnerRow(id=new_id, created_at=created_at)
            db.add(row)
            db.commit()
            return Learner(id=new_id, created_at=created_at)

    def get(self, learner_id: str) -> Learner | None:
        """Load a learner by id, or ``None`` if absent."""
        with self._session_factory() as db:
            row = db.get(LearnerRow, learner_id)
            if row is None:
                return None
            return self._learner_row_to_domain(row)

    def get_progress(
        self, learner_id: str, module_id: str
    ) -> ModuleProgress | None:
        """Load the learner's progress on ``module_id``, or ``None`` if absent."""
        with self._session_factory() as db:
            row = db.get(LearnerModuleProgressRow, (learner_id, module_id))
            if row is None:
                return None
            return self._progress_row_to_domain(row)

    def save_progress(self, progress: ModuleProgress) -> None:
        """Upsert the learner's per-module progress (θ + mastery).

        Keyed by ``(learner_id, module_id)``: an existing row is updated in
        place, otherwise a new one is inserted. The mastery list is serialised
        wholesale to the JSON blob column.
        """
        with self._session_factory() as db:
            row = db.get(
                LearnerModuleProgressRow,
                (progress.learner_id, progress.module_id),
            )
            if row is None:
                row = LearnerModuleProgressRow(
                    learner_id=progress.learner_id,
                    module_id=progress.module_id,
                )
                db.add(row)
            row.theta = progress.theta
            row.mastery_json = self._mastery_to_json(progress.mastery)
            row.updated_at = _as_utc(progress.updated_at)
            db.commit()

    def list_progress_modules(self, learner_id: str) -> list[str]:
        """Return the module ids the learner has any progress on."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(LearnerModuleProgressRow.module_id).where(
                    LearnerModuleProgressRow.learner_id == learner_id
                )
            )
            return list(rows)

    def link_learner_to_user(self, learner_id: str, user_id: str) -> None:
        """Set ``learners.user_id`` for an existing learner (no-op if absent)."""
        with self._session_factory() as db:
            row = db.get(LearnerRow, learner_id)
            if row is None:
                return
            row.user_id = user_id
            db.commit()

    def list_learners_for_user(self, user_id: str) -> list[Learner]:
        """Return all learners owned by ``user_id`` (empty if none)."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(LearnerRow).where(LearnerRow.user_id == user_id)
            )
            return [self._learner_row_to_domain(r) for r in rows]

    def create_learner_for_user(
        self, user_id: str, now: datetime
    ) -> Learner:
        """Mint a new learner already owned by ``user_id`` (atomic)."""
        created_at = _as_utc(now)
        new_id = str(uuid4())
        with self._session_factory() as db:
            db.add(
                LearnerRow(
                    id=new_id, created_at=created_at, user_id=user_id
                )
            )
            db.commit()
            return Learner(id=new_id, created_at=created_at, user_id=user_id)


class UserRepository(abc.ABC):
    """Persistence boundary for authenticated user accounts.

    A user (Firebase uid as id) owns zero or more :class:`Learner` rows via the
    learners' optional ``user_id``. All methods exchange the
    :class:`~math_practice_backend.domain.User` dataclass only; implementations
    must not expose ORM rows to callers.
    """

    @abc.abstractmethod
    def get(self, user_id: str) -> User | None:
        """Load a user by id, or ``None`` if it does not exist."""

    @abc.abstractmethod
    def upsert(self, user: User) -> None:
        """Insert the user, or update ``email``/``created_at`` if it exists."""

    @abc.abstractmethod
    def get_or_create(
        self, user_id: str, email: str | None, now: datetime
    ) -> User:
        """Return an existing user, or create one stamped at ``now``.

        When ``user_id`` names an existing user it is returned unchanged.
        Otherwise a new user is created with the given ``email`` and
        ``created_at`` taken from the caller's clock (``now``).
        """


class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy 2.0 implementation backed by a :class:`sessionmaker`.

    A fresh :class:`~sqlalchemy.orm.Session` is opened and committed/rolled back
    per public call, keeping the repository stateless and thread-safe for the
    shared in-memory engine.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        """Bind the repository to a session factory.

        Args:
            session_factory: a configured :class:`~sqlalchemy.orm.sessionmaker`
                bound to the application engine.
        """
        self._session_factory = session_factory

    @staticmethod
    def _user_row_to_domain(row: UserRow) -> User:
        """Map a ``users`` ORM row to a :class:`User`."""
        return User(
            id=row.id,
            email=row.email,
            created_at=_as_utc(row.created_at),
        )

    def get(self, user_id: str) -> User | None:
        """Load a user by id, or ``None`` if absent."""
        with self._session_factory() as db:
            row = db.get(UserRow, user_id)
            if row is None:
                return None
            return self._user_row_to_domain(row)

    def upsert(self, user: User) -> None:
        """Insert the user, or update ``email``/``created_at`` in place."""
        with self._session_factory() as db:
            row = db.get(UserRow, user.id)
            if row is None:
                row = UserRow(id=user.id)
                db.add(row)
            row.email = user.email
            row.created_at = _as_utc(user.created_at)
            db.commit()

    def get_or_create(
        self, user_id: str, email: str | None, now: datetime
    ) -> User:
        """Return an existing user, or create one stamped at ``now``."""
        created_at = _as_utc(now)
        with self._session_factory() as db:
            row = db.get(UserRow, user_id)
            if row is not None:
                return self._user_row_to_domain(row)
            row = UserRow(id=user_id, email=email, created_at=created_at)
            db.add(row)
            db.commit()
            return User(id=user_id, email=email, created_at=created_at)
