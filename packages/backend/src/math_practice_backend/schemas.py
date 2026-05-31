"""Pydantic v2 schemas for the HTTP edge (request/response bodies).

These models live *only* at the API boundary. Internal components exchange the
plain dataclasses from :mod:`math_practice_backend.domain` and the engine's
:class:`~math_practice.EngineState`; the explicit mapping between the two lives
in :mod:`math_practice_backend.mappers`.

:class:`ConfigOverrides` mirrors every field of
:class:`~math_practice.EngineConfig` but makes each optional, so a client may
override an arbitrary subset of the engine hyper-parameters when creating a
session. :meth:`ConfigOverrides.to_overrides` collapses it to a dict of only the
explicitly-set (non-``None``) fields, ready to feed the engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class HealthOut(BaseModel):
    """Liveness probe payload."""

    status: str


class ConfigOverrides(BaseModel):
    """Optional partial override of :class:`~math_practice.EngineConfig`.

    Every field is optional; only the explicitly-provided ones are applied. Use
    :meth:`to_overrides` to obtain a dict of the set (non-``None``) values.
    """

    MAX_SUM: int | None = None
    w_mag: float | None = None
    w_order: float | None = None
    w_double: float | None = None
    TIME_LIMIT: float | None = None
    tau_time: float | None = None
    p_time: float | None = None
    slow_correct_credit: float | None = None
    K: float | None = None
    difficulty_scale: float | None = None
    p_target: float | None = None
    p_start: float | None = None
    selection_temperature: float | None = None
    epsilon: float | None = None
    mastery_streak: int | None = None
    mastery_time_limit: float | None = None
    max_faults: int | None = None

    def to_overrides(self) -> dict[str, Any]:
        """Return a dict of only the explicitly-set (non-``None``) overrides."""
        return self.model_dump(exclude_none=True)


class CreateSessionIn(BaseModel):
    """Request body for creating a new session."""

    config: ConfigOverrides | None = None


class ProgressOut(BaseModel):
    """Mastery/ability progress snapshot for a session."""

    theta: float
    mastered_count: int
    total: int
    all_mastered: bool


class ExerciseOut(BaseModel):
    """A drawn (pending) exercise presented to the client."""

    a: int
    b: int
    op: str
    issued_at: datetime


class SessionOut(BaseModel):
    """Full session view returned on create/get."""

    session_id: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    progress: ProgressOut
    pending: ExerciseOut | None = None


class AnswerIn(BaseModel):
    """Client-submitted answer with its own measured elapsed time."""

    answer: int
    elapsed_seconds: float

    @field_validator("elapsed_seconds")
    @classmethod
    def _non_negative_elapsed(cls, value: float) -> float:
        """Reject negative elapsed times."""
        if value < 0:
            raise ValueError("elapsed_seconds must be >= 0")
        return value


class MasteryOut(BaseModel):
    """Per-exercise mastery bookkeeping after a trial."""

    streak: int
    faults: int
    mastered: bool


class TrialOut(BaseModel):
    """The graded result of a single submitted answer."""

    seq: int
    a: int
    b: int
    correct: bool
    response_time: float
    s: float
    E: float
    theta_before: float
    theta_after: float
    mastery: MasteryOut
    progress: ProgressOut


class StatsOut(BaseModel):
    """Aggregate session statistics with a recent-trials tail."""

    progress: ProgressOut
    trials: int
    correct: int
    accuracy: float
    recent: list[TrialOut] = Field(default_factory=list)


# ----- student-safe schemas (the /v1/play API edge) ------------------------
#
# These omit every engine internal (theta, mastered_count, total, score ``s``,
# predicted success ``E``). They are the *only* shapes the static web client
# ever sees.


class StudentSessionOut(BaseModel):
    """Student-safe view returned when a play session is created."""

    session_id: str
    expires_at: datetime


class StudentAnswerOut(BaseModel):
    """Student-safe result of submitting an answer.

    Carries only the freshly-recomputed surface metrics: whether the answer was
    correct plus the post-answer counts the UI shows (questions done, module
    completion percentage, current correct streak).
    """

    correct: bool
    questions_done: int
    module_completion_percent: float
    streak: int


class StudentStatsOut(BaseModel):
    """Student-safe aggregate statistics for a play session."""

    questions_done: int
    correct: int
    accuracy: float
    total_time_seconds: float
    avg_time_seconds: float
    module_completion_percent: float
    streak: int
