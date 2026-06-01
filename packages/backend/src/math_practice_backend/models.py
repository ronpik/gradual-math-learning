"""SQLAlchemy 2.0 ORM models for the math-practice persistence layer.

Permanent learner identity and resumable per-module progress:

* ``learners`` — one row per learner: a permanent id (stored client-side in
  ``localStorage``) and its creation time.
* ``learner_module_progress`` — resumable per-``(learner, module)`` state,
  keyed by ``(learner_id, module_id)``: the engine's latent ability and a JSON
  blob of per-exercise mastery, write-through on every graded answer.

Three tables back a practice session:

* ``sessions`` — one row per session: the owning learner, the chosen module and
  practice mode, lifecycle metadata (timestamps, status, stop-rule targets), the
  engine's latent ability and serialised :class:`~math_practice.EngineConfig`
  (JSON), the last-shown exercise, the currently-pending (unanswered) exercise,
  the next-trial sequence counter, and denormalised headline metrics.
* ``session_mastery`` — per-exercise mastery bookkeeping, keyed by
  ``(session_id, a, b)``.
* ``trials`` — the append-only graded-trial log (engine diagnostic trace).
* ``session_exercises`` — the per-session audit log: one student-facing row per
  answered question (no engine internals).

All datetimes are timezone-aware UTC. These ORM rows never cross the repository
boundary: the repository maps them to/from the domain dataclasses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class LearnerRow(Base):
    """ORM row for a permanent learner identity (``learners`` table)."""

    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LearnerModuleProgressRow(Base):
    """ORM row for resumable per-``(learner, module)`` progress.

    Keyed by ``(learner_id, module_id)``; stores the engine's latent ability and
    a JSON blob of per-exercise mastery (a list of
    ``{a, b, streak, faults, mastered}``). Written through on every graded answer
    so progress survives an abandoned session (``learner_module_progress``
    table).
    """

    __tablename__ = "learner_module_progress"

    learner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("learners.id", ondelete="CASCADE"),
        primary_key=True,
    )
    module_id: Mapped[str] = mapped_column(String, primary_key=True)

    theta: Mapped[float] = mapped_column(Float, nullable=False)
    mastery_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SessionRow(Base):
    """ORM row for a practice session (``sessions`` table).

    Beyond the engine snapshot (``theta``/``config``/last-shown/pending), each
    session records the owning learner, the chosen module and practice mode, its
    lifecycle (``started_at``/``ended_at``/``status``), the mode stop-rule targets
    (``target_count``/``target_seconds``), and denormalised headline metrics
    (``questions_done``/``correct_count``/``total_time``) so the summary is a
    cheap read. The composite ``(learner_id, module_id, mode)`` index backs the
    personal-best query.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("learners.id"),
        nullable=False,
        index=True,
    )
    module_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    theta: Mapped[float] = mapped_column(Float, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    last_shown_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_shown_b: Mapped[int | None] = mapped_column(Integer, nullable=True)

    pending_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trial_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    questions_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_time: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    mastery: Mapped[list["MasteryRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    trials: Mapped[list["TrialRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    exercises: Mapped[list["SessionExerciseRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_sessions_learner_module_mode", "learner_id", "module_id", "mode"),
    )


class MasteryRow(Base):
    """ORM row for one exercise's mastery state (``session_mastery`` table)."""

    __tablename__ = "session_mastery"

    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    a: Mapped[int] = mapped_column(Integer, primary_key=True)
    b: Mapped[int] = mapped_column(Integer, primary_key=True)

    streak: Mapped[int] = mapped_column(Integer, nullable=False)
    faults: Mapped[int] = mapped_column(Integer, nullable=False)
    mastered: Mapped[bool] = mapped_column(Boolean, nullable=False)

    session: Mapped[SessionRow] = relationship(back_populates="mastery")


class TrialRow(Base):
    """ORM row for one graded trial (``trials`` table)."""

    __tablename__ = "trials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    a: Mapped[int] = mapped_column(Integer, nullable=False)
    b: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_time: Mapped[float] = mapped_column(Float, nullable=False)

    s: Mapped[float] = mapped_column(Float, nullable=False)
    e: Mapped[float] = mapped_column(Float, nullable=False)
    theta_before: Mapped[float] = mapped_column(Float, nullable=False)
    theta_after: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    session: Mapped[SessionRow] = relationship(back_populates="trials")


class SessionExerciseRow(Base):
    """ORM row for one answered question's audit record (``session_exercises``).

    The clean student/audit log: one row per answered question carrying the
    rendered exercise (``a``, ``b``, ``op``), its structural ``level``, the
    learner's ``given_answer``, whether it was ``correct``, the ``elapsed`` answer
    time, and the per-session ``seq`` ordinal. Unlike ``trials`` it holds no
    engine internals (no ``theta``/``s``/``E``).
    """

    __tablename__ = "session_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    a: Mapped[int] = mapped_column(Integer, nullable=False)
    b: Mapped[int] = mapped_column(Integer, nullable=False)
    op: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    given_answer: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    elapsed: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    session: Mapped[SessionRow] = relationship(back_populates="exercises")
