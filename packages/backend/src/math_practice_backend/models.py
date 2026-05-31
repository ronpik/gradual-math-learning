"""SQLAlchemy 2.0 ORM models for the math-practice persistence layer.

Three tables back a practice session:

* ``sessions`` — one row per session: metadata (timestamps), the engine's
  latent ability and serialised :class:`~math_practice.EngineConfig` (JSON),
  the last-shown exercise, the currently-pending (unanswered) exercise, and the
  next-trial sequence counter.
* ``session_mastery`` — per-exercise mastery bookkeeping, keyed by
  ``(session_id, a, b)``.
* ``trials`` — the append-only graded-trial log.

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
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class SessionRow(Base):
    """ORM row for a practice session (``sessions`` table)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

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

    mastery: Mapped[list["MasteryRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    trials: Mapped[list["TrialRow"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
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
