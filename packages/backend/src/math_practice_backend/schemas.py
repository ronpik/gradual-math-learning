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
    op: str | None = None
    range_bound: int | None = None
    w_mag: float | None = None
    w_order: float | None = None
    w_double: float | None = None
    w_sub: float | None = None
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
    """Request body for creating a new (admin) session.

    ``module_id`` and ``mode`` select the practice run; both are optional for
    back-compat with the v1 admin surface (omitting them defaults to the
    ``add_10`` module in endless mode). ``config`` may override individual engine
    hyper-parameters on top of the resolved module config.
    """

    module_id: str | None = None
    mode: str | None = None
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
    """Full session view returned on create/get (admin surface).

    Carries the run's module/mode/status alongside the engine-internal progress
    so the admin/diagnostic API can see which kind of run a session is and where
    in its lifecycle it sits.
    """

    session_id: str
    module_id: str
    mode: str
    status: str
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


class SessionExerciseOut(BaseModel):
    """A single row of the per-session clean audit log (admin surface).

    Mirrors :class:`~math_practice_backend.domain.SessionExercise`: the
    student-visible facts of one answered question with no engine internals
    (no ``s``/``E``/``theta``).
    """

    seq: int
    a: int
    b: int
    op: str
    level: int
    given_answer: int
    correct: bool
    elapsed: float
    created_at: datetime


# ----- student-safe schemas (the /v1/play API edge) ------------------------
#
# These omit every engine internal (theta, mastered_count, total, score ``s``,
# predicted success ``E``). They are the *only* shapes the static web client
# ever sees.


class ModuleOut(BaseModel):
    """A practice-module descriptor for the main screen.

    The student-safe view of a :class:`~math_practice.ModuleSpec`: which
    operation and range the module covers, a display label, and the structural
    difficulty levels its range permits (for the per-level completion display).
    No engine internals (config knobs, scorer) are exposed.
    """

    id: str
    op: str
    range_bound: int
    label: str
    levels: list[int]


class ModeOut(BaseModel):
    """A practice-mode descriptor for the main screen.

    Describes one selectable mode (stop rule + headline metric) by id, display
    label, and a short human-readable description.
    """

    id: str
    label: str
    description: str


class CreateStudentSessionIn(BaseModel):
    """Request body for creating a play session.

    ``learner_id`` is optional: when missing or unknown the server mints a fresh
    learner and returns its id (the client persists it). ``module_id`` and
    ``mode`` select the practice run.
    """

    learner_id: str | None = None
    module_id: str
    mode: str


class MeOut(BaseModel):
    """The authenticated user's identity + their account learner.

    Returned by ``GET /v1/play/me``. Carries the durable ``learner_id`` the
    client plays as once signed in, and the user's email (if known). No engine
    internals.
    """

    learner_id: str
    email: str | None = None


class ClaimIn(BaseModel):
    """Request body for ``POST /v1/play/claim``.

    Names the anonymous (localStorage) learner whose cross-session progress
    should be folded into the authenticated user's account learner.
    """

    anonymous_learner_id: str


class ClaimOut(BaseModel):
    """Result of ``POST /v1/play/claim``: the user's learner after the merge."""

    learner_id: str


class StudentSessionOut(BaseModel):
    """Student-safe view returned when a play session is created.

    Carries the identity the client persists (``session_id`` + ``learner_id``),
    the chosen ``module_id`` / ``mode``, the 24h expiry, and the mode's stop-rule
    parameters. ``deadline`` is ``started_at + target_seconds`` for the timed
    3-minute mode and ``None`` otherwise, so a timed client can drive its
    countdown off the server-authoritative deadline.
    """

    session_id: str
    learner_id: str
    module_id: str
    mode: str
    started_at: datetime
    expires_at: datetime
    target_count: int | None = None
    target_seconds: int | None = None
    deadline: datetime | None = None


class StudentAnswerOut(BaseModel):
    """Student-safe result of submitting an answer.

    Carries only the freshly-recomputed surface metrics: whether the answer was
    correct, the post-answer counts the UI shows (questions done, module
    completion percentage, current correct streak), whether the run is now
    finished, and the mode's "what is left" payload (``seconds_left`` for the
    timed mode, ``questions_left`` for the count-bound mode, both ``None``
    otherwise). No engine internals leak.
    """

    correct: bool
    questions_done: int
    module_completion_percent: float
    streak: int
    finished: bool
    seconds_left: float | None = None
    questions_left: int | None = None


class StudentStatsOut(BaseModel):
    """Student-safe aggregate statistics for a play session."""

    questions_done: int
    correct: int
    accuracy: float
    total_time_seconds: float
    avg_time_seconds: float
    module_completion_percent: float
    streak: int


class LevelProgressOut(BaseModel):
    """Per-level completion counts (student-safe).

    The per-level mastered/total counts surfaced on the summary; never any
    engine internals (theta, scores).
    """

    level: int
    mastered: int
    total: int


class StudentSummaryOut(BaseModel):
    """Student-safe end-of-run summary for a play session.

    The mode's headline metric plus the personal best (and whether this run beat
    it) and per-level mastery. ``headline`` is the mode-specific payload
    (``total_time_seconds`` / ``questions_done`` / ``accuracy``);
    ``personal_best`` is ``None`` for modes without a best (Endless) or when none
    exists yet. No engine internals (theta, ``s``, ``E``, total mastered counts)
    cross this boundary.
    """

    module_id: str
    label: str
    mode: str
    status: str
    questions_done: int
    correct: int
    accuracy: float
    total_time_seconds: float
    avg_time_seconds: float
    headline: dict[str, Any]
    personal_best: float | None = None
    is_new_best: bool
    levels: list[LevelProgressOut] = Field(default_factory=list)
