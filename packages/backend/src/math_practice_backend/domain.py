"""Internal domain dataclasses for the backend (the persistence boundary).

These plain dataclasses are the *only* objects passed between the service,
repository, and mapper layers — never raw dicts and never ORM rows. Pydantic
schemas live exclusively at the HTTP edge and are mapped to/from these types.

The :class:`SessionAggregate` carries a session's metadata plus the engine's
restorable :class:`~math_practice.EngineState`. Trials are deliberately *not*
embedded in the aggregate: they are appended and queried through dedicated
repository methods to keep the aggregate small and the trial log append-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from math_practice import EngineState


@dataclass
class PendingExercise:
    """An exercise that has been drawn and shown but not yet answered.

    Attributes:
        a:         first operand.
        b:         second operand.
        issued_at: when the exercise was drawn (aware UTC).
    """

    a: int
    b: int
    issued_at: datetime


@dataclass
class TrialRecord:
    """A single graded trial, persisted to the append-only trial log.

    Attributes:
        seq:           monotonic per-session sequence number (1-based).
        a:             first operand.
        b:             second operand.
        correct:       whether the answer was graded correct (and in time).
        response_time: client-measured elapsed seconds.
        s:             trial score produced by the engine.
        E:             predicted success probability for the item.
        theta_before:  latent ability before applying the trial.
        theta_after:   latent ability after applying the trial.
        created_at:    when the trial was recorded (aware UTC).
    """

    seq: int
    a: int
    b: int
    correct: bool
    response_time: float
    s: float
    E: float
    theta_before: float
    theta_after: float
    created_at: datetime


@dataclass
class SessionAggregate:
    """The full restorable state of a practice session.

    Attributes:
        id:               opaque session id (uuid4 hex).
        created_at:       creation time (aware UTC).
        last_activity_at: last session-scoped activity (aware UTC), slid forward
                          on every request.
        expires_at:       ``last_activity_at + ttl`` (aware UTC).
        engine_state:     restorable snapshot of the practice engine.
        pending:          the currently-shown, unanswered exercise, if any.
        trial_seq:        counter for the next trial's sequence number.
    """

    id: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    engine_state: EngineState
    pending: PendingExercise | None
    trial_seq: int
