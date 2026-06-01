"""Internal domain dataclasses for the backend (the persistence boundary).

These plain dataclasses are the *only* objects passed between the service,
repository, and mapper layers — never raw dicts and never ORM rows. Pydantic
schemas live exclusively at the HTTP edge and are mapped to/from these types.

The domain models four concepts: a permanent :class:`Learner`; the resumable
per-(learner, module) :class:`ModuleProgress` that seeds and is written through
on every answer; a single ephemeral :class:`SessionAggregate` (one run of one
``(module, mode)``) carrying the engine's restorable
:class:`~math_practice.EngineState`; and the :class:`SessionExercise` audit row.

Trials are deliberately *not* embedded in the aggregate: both the engine
diagnostic trace (:class:`TrialRecord`) and the clean :class:`SessionExercise`
audit log are appended and queried through dedicated repository methods to keep
the aggregate small and both logs append-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from math_practice import EngineState, ExerciseMastery

from .enums import Mode, SessionStatus


@dataclass
class Learner:
    """A permanent learner identity.

    The learner id is minted by the server on first contact and stored by the
    client (``localStorage``); it scopes all of a child's cross-session module
    progress.

    Attributes:
        id:         opaque learner id (uuid4 hex).
        created_at: when the learner was first created (aware UTC).
    """

    id: str
    created_at: datetime


@dataclass
class ModuleProgress:
    """Resumable per-(learner, module) practice state.

    This is the durable θ + mastery for one learner on one module, written
    through after every graded answer so progress survives an abandoned session
    and seeds the engine when a new session for the same pair is created.

    Attributes:
        learner_id: the owning learner's id.
        module_id:  the module this progress is for (e.g. ``"add_20"``).
        theta:      the learner's latent ability on this module.
        mastery:    per-exercise mastery records (engine value objects).
        updated_at: when the progress was last written (aware UTC).
    """

    learner_id: str
    module_id: str
    theta: float
    mastery: list[ExerciseMastery]
    updated_at: datetime


@dataclass
class PendingExercise:
    """An exercise that has been drawn and shown but not yet answered.

    Attributes:
        a:         first operand (minuend for subtraction).
        b:         second operand (subtrahend for subtraction).
        issued_at: when the exercise was drawn (aware UTC).
        op:        the operator (``"+"`` or ``"-"``), so the client can render it.
    """

    a: int
    b: int
    issued_at: datetime
    op: str = "+"


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
class SessionExercise:
    """A single answered question, persisted to the clean per-session audit log.

    Distinct from :class:`TrialRecord`: this row carries no engine internals
    (θ/s/E), only the student-visible facts of the question and the answer. One
    row is written per graded answer, alongside the engine trace.

    Attributes:
        seq:          monotonic per-session sequence number (1-based).
        a:            first operand (minuend for subtraction).
        b:            second operand (subtrahend for subtraction).
        op:           the operator (``"+"`` or ``"-"``).
        level:        the exercise's structural difficulty level (1..5).
        given_answer: the answer the learner submitted.
        correct:      whether the answer was graded correct (and in time).
        elapsed:      client-measured elapsed seconds.
        created_at:   when the answer was recorded (aware UTC).
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


@dataclass
class SessionAggregate:
    """The full restorable state of a single practice run.

    A session is one run of one ``(module, mode)`` for one learner. It is
    ephemeral (24h sliding expiry) while the learner's progress lives on in
    :class:`ModuleProgress`. The mode contributes only a stop rule and a headline
    metric; ``started_at`` equals ``created_at`` so a timed mode's deadline is
    known at creation.

    Attributes:
        id:               opaque session id (uuid4 hex).
        learner_id:       the owning learner's id.
        module_id:        the module being practiced (e.g. ``"sub_20"``).
        mode:             the practice mode (stop rule + headline metric).
        status:           lifecycle state (active/completed/expired/abandoned).
        created_at:       creation time (aware UTC).
        started_at:       when the run began (aware UTC); equals ``created_at``.
        ended_at:         when the run completed (aware UTC), if it has.
        last_activity_at: last session-scoped activity (aware UTC), slid forward
                          on every request.
        expires_at:       ``last_activity_at + ttl`` (aware UTC).
        target_count:     answers required to complete (``20`` for Fastest-20),
                          or ``None`` when the mode has no count target.
        target_seconds:   run duration in seconds (``180`` for 3-minute), or
                          ``None`` when the mode is untimed.
        engine_state:     restorable snapshot of the practice engine.
        pending:          the currently-shown, unanswered exercise, if any.
        trial_seq:        counter for the next trial's sequence number.
        questions_done:   denormalized count of answered questions.
        correct_count:    denormalized count of correct answers.
        total_time:       denormalized sum of elapsed answer times (seconds).
    """

    id: str
    learner_id: str
    module_id: str
    mode: Mode
    status: SessionStatus
    created_at: datetime
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    expires_at: datetime
    target_count: int | None
    target_seconds: int | None
    engine_state: EngineState
    pending: PendingExercise | None
    trial_seq: int
    questions_done: int
    correct_count: int
    total_time: float
