"""Repository layer for practice sessions.

Defines the :class:`SessionRepository` abstract interface and a SQLAlchemy 2.0
implementation. The repository is the *only* place ORM rows exist: every public
method accepts and returns the domain dataclasses
(:class:`~math_practice_backend.domain.SessionAggregate`,
:class:`~math_practice_backend.domain.TrialRecord`) and the engine value objects
(:class:`~math_practice.EngineState`,
:class:`~math_practice.ExerciseMastery`,
:class:`~math_practice.EngineConfig`). ORM objects never leak out.

The repository owns serialisation: :class:`EngineConfig` maps to/from a JSON
column via :func:`dataclasses.asdict` / ``EngineConfig(**d)``; mastery maps
to/from ``session_mastery`` rows; and last-shown/pending exercises map to/from
nullable columns.
"""

from __future__ import annotations

import abc
import dataclasses
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from math_practice import EngineConfig, EngineState, ExerciseMastery

from .domain import PendingExercise, SessionAggregate, TrialRecord
from .models import MasteryRow, SessionRow, TrialRow


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
        row.created_at = agg.created_at
        row.last_activity_at = agg.last_activity_at
        row.expires_at = agg.expires_at
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
            )
        return SessionAggregate(
            id=row.id,
            created_at=_as_utc(row.created_at),
            last_activity_at=_as_utc(row.last_activity_at),
            expires_at=_as_utc(row.expires_at),
            engine_state=engine_state,
            pending=pending,
            trial_seq=row.trial_seq,
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
