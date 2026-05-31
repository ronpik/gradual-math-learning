"""Session orchestration service (the application/use-case layer).

:class:`SessionService` is the single seam between the HTTP layer and the
persistence + engine layers. It owns the session lifecycle:

    * **create** — validate config overrides, build a fresh
      :class:`~math_practice.PracticeEngine`, snapshot it, and persist a new
      :class:`~math_practice_backend.domain.SessionAggregate`.
    * **load + slide** — every session-scoped operation loads the aggregate,
      enforces the sliding-TTL expiry, and refreshes ``last_activity_at`` /
      ``expires_at``.
    * **next** — draw (or re-show) the pending exercise.
    * **answer** — grade against the server-known sum, update the engine, append
      a trial, and clear the pending exercise.
    * **stats** — aggregate progress and the recent trial log.

Everything crossing this boundary is a dataclass; Pydantic lives only at the
HTTP edge. Mutating operations are guarded by a per-session lock so concurrent
``next``/``answer`` calls on one session are serialised.
"""

from __future__ import annotations

import random
import threading
import uuid
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Callable, NamedTuple

from math_practice import (
    EngineConfig,
    EngineState,
    Exercise,
    ExerciseMastery,
    PracticeEngine,
)

from .clock import Clock
from .domain import PendingExercise, SessionAggregate, TrialRecord
from .errors import (
    InvalidConfig,
    NoPendingExercise,
    SessionExpired,
    SessionNotFound,
)
from .repositories import SessionRepository


class Progress(NamedTuple):
    """Progress projection for a session (engine-derived, no ORM).

    Attributes:
        theta:          current latent ability.
        mastered_count: number of mastered curriculum exercises.
        total:          total number of curriculum exercises.
        all_mastered:   ``True`` when every exercise is mastered.
    """

    theta: float
    mastered_count: int
    total: int
    all_mastered: bool


class AnswerOutcome(NamedTuple):
    """Result bundle returned by :meth:`SessionService.submit_answer`.

    Attributes:
        trial:    the persisted :class:`TrialRecord`.
        mastery:  the post-trial mastery state for the answered exercise.
        progress: session progress after applying the trial.
    """

    trial: TrialRecord
    mastery: ExerciseMastery
    progress: Progress


class StatsResult(NamedTuple):
    """Result bundle returned by :meth:`SessionService.get_stats`.

    Attributes:
        aggregate: the (slid) session aggregate.
        progress:  session progress.
        trials:    total number of recorded trials.
        correct:   number of correct trials.
        recent:    the most recent trials (newest-first, capped).
    """

    aggregate: SessionAggregate
    progress: Progress
    trials: int
    correct: int
    recent: list[TrialRecord]


class SessionService:
    """Use-case orchestration for practice sessions.

    Wires a :class:`~math_practice_backend.repositories.SessionRepository`, a
    :class:`~math_practice_backend.clock.Clock`, a sliding TTL, and an RNG
    factory into the session lifecycle. The service is stateless except for a
    lazily-built table of per-session locks; all durable state lives in the
    repository.
    """

    def __init__(
        self,
        repo: SessionRepository,
        clock: Clock,
        ttl: timedelta,
        rng_factory: Callable[[], random.Random] = lambda: random.Random(),
    ) -> None:
        """Build the service.

        Args:
            repo:        the session persistence boundary.
            clock:       source of aware-UTC "now".
            ttl:         sliding retention window; ``expires_at = now + ttl``.
            rng_factory: factory producing a fresh :class:`random.Random` for
                each engine rehydration (kept injectable for determinism).
        """
        self._repo = repo
        self._clock = clock
        self._ttl = ttl
        self._rng_factory = rng_factory
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ----- locking ----------------------------------------------------------

    def _lock_for(self, sid: str) -> threading.Lock:
        """Return the per-session lock for ``sid``, creating it on first use."""
        with self._locks_guard:
            lock = self._locks.get(sid)
            if lock is None:
                lock = threading.Lock()
                self._locks[sid] = lock
            return lock

    # ----- progress helpers -------------------------------------------------

    @staticmethod
    def progress(agg: SessionAggregate) -> Progress:
        """Compute progress directly from an aggregate's engine state.

        Reading mastery off the persisted :class:`EngineState` avoids the cost
        of rehydrating an engine just to count mastered items.

        Args:
            agg: the session aggregate.

        Returns:
            The :class:`Progress` projection.
        """
        return SessionService._progress_from_state(agg.engine_state)

    @staticmethod
    def _progress_from_state(state: EngineState) -> Progress:
        """Build a :class:`Progress` from an :class:`EngineState`."""
        total = len(state.mastery)
        mastered_count = sum(1 for m in state.mastery if m.mastered)
        return Progress(
            theta=state.theta,
            mastered_count=mastered_count,
            total=total,
            all_mastered=total > 0 and mastered_count >= total,
        )

    # ----- config validation ------------------------------------------------

    @staticmethod
    def _build_config(overrides: dict | None) -> EngineConfig:
        """Validate overrides and build an :class:`EngineConfig`.

        Unknown keys and type-incompatible values both raise
        :class:`InvalidConfig`. ``None`` / empty overrides yield the default
        config.

        Args:
            overrides: optional partial mapping of ``EngineConfig`` field names
                to values.

        Returns:
            The constructed (frozen) :class:`EngineConfig`.

        Raises:
            InvalidConfig: on unknown keys or invalid values.
        """
        if not overrides:
            return EngineConfig()

        field_types = {f.name: f.type for f in fields(EngineConfig)}
        unknown = sorted(set(overrides) - set(field_types))
        if unknown:
            raise InvalidConfig(f"Unknown config field(s): {', '.join(unknown)}")

        coerced: dict = {}
        for name, value in overrides.items():
            expected = field_types[name]
            # Field annotations are simple ("int"/"float"); coerce numerics so
            # an int passed for a float field is accepted, reject the rest.
            if expected == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise InvalidConfig(
                        f"Config field {name!r} expects an int, got "
                        f"{type(value).__name__}"
                    )
                coerced[name] = value
            elif expected == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise InvalidConfig(
                        f"Config field {name!r} expects a number, got "
                        f"{type(value).__name__}"
                    )
                coerced[name] = float(value)
            else:
                coerced[name] = value

        try:
            config = EngineConfig(**coerced)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise InvalidConfig(f"Invalid config overrides: {exc}") from exc

        if config.MAX_SUM < 2:
            raise InvalidConfig("Config field 'MAX_SUM' must be >= 2")
        return config

    # ----- load / expiry / slide -------------------------------------------

    def _load(self, sid: str, *, persist_slide: bool = False) -> SessionAggregate:
        """Load a session, enforce expiry, and slide its activity window.

        Loads the aggregate via the repository. If absent, raises
        :class:`SessionNotFound`. If ``expires_at <= now`` the session is
        deleted and :class:`SessionExpired` is raised. Otherwise the activity
        window is slid forward (``last_activity_at = now``,
        ``expires_at = now + ttl``).

        Mutating callers (``get_next``/``submit_answer``) persist the slide as
        part of their own ``save``; read-only callers pass
        ``persist_slide=True`` so the slide is durably recorded here.

        Args:
            sid:           the session id.
            persist_slide: when ``True``, persist the slid aggregate immediately.

        Returns:
            The loaded, slid :class:`SessionAggregate`.

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session's retention window has elapsed.
        """
        agg = self._repo.get(sid)
        if agg is None:
            raise SessionNotFound(sid)

        now = self._clock.now()
        if agg.expires_at <= now:
            self._repo.delete(sid)
            raise SessionExpired(sid)

        agg.last_activity_at = now
        agg.expires_at = now + self._ttl
        if persist_slide:
            self._repo.save(agg)
        return agg

    # ----- public use cases -------------------------------------------------

    def create_session(self, overrides: dict | None = None) -> SessionAggregate:
        """Create and persist a brand-new practice session.

        Validates ``overrides`` into an :class:`EngineConfig`, builds a fresh
        :class:`PracticeEngine`, snapshots it, and persists a new aggregate with
        a uuid4-hex id, timestamps, ``expires_at = now + ttl``, no pending
        exercise, and ``trial_seq = 0``.

        Args:
            overrides: optional partial ``EngineConfig`` field overrides.

        Returns:
            The newly created :class:`SessionAggregate`.

        Raises:
            InvalidConfig: if any override is unknown or invalid.
        """
        config = self._build_config(overrides)
        engine = PracticeEngine(config=config, rng=self._rng_factory())
        state = engine.snapshot()

        now = self._clock.now()
        agg = SessionAggregate(
            id=uuid.uuid4().hex,
            created_at=now,
            last_activity_at=now,
            expires_at=now + self._ttl,
            engine_state=state,
            pending=None,
            trial_seq=0,
        )
        self._repo.create(agg)
        return agg

    def get_session(self, sid: str) -> SessionAggregate:
        """Load a session, enforcing expiry and persisting the activity slide.

        Args:
            sid: the session id.

        Returns:
            The slid :class:`SessionAggregate`.

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
        """
        return self._load(sid, persist_slide=True)

    def get_next(self, sid: str) -> PendingExercise:
        """Return the pending exercise, drawing a new one if none is pending.

        Guarded by the per-session lock. If a pending exercise already exists it
        is returned unchanged (resume re-show). Otherwise the engine is
        rehydrated, a new exercise is drawn, recorded as the pending exercise,
        and the updated engine snapshot (capturing ``last_shown``) is persisted.

        Args:
            sid: the session id.

        Returns:
            The pending :class:`PendingExercise`.

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
        """
        with self._lock_for(sid):
            agg = self._load(sid)

            if agg.pending is not None:
                self._repo.save(agg)  # persist the activity slide
                return agg.pending

            engine = PracticeEngine.from_state(
                agg.engine_state, rng=self._rng_factory()
            )
            exercise = engine.next_exercise()
            now = self._clock.now()
            pending = PendingExercise(
                a=exercise.a, b=exercise.b, issued_at=now
            )
            agg.pending = pending
            agg.engine_state = engine.snapshot()
            self._repo.save(agg)
            return pending

    def submit_answer(
        self, sid: str, answer: int, elapsed: float
    ) -> AnswerOutcome:
        """Grade an answer, update the engine, persist a trial, clear pending.

        Guarded by the per-session lock. The pending exercise is required
        (otherwise :class:`NoPendingExercise`). Correctness is graded
        server-side: ``answer == a + b`` *and* ``elapsed < config.TIME_LIMIT``.
        The engine is rehydrated and asked to grade the trial; the resulting
        before/after ability, score, and predicted success are recorded into a
        :class:`TrialRecord`. The engine snapshot and bumped ``trial_seq`` are
        persisted, the pending exercise is cleared, and the trial is appended to
        the log.

        Args:
            sid:     the session id.
            answer:  the learner's numeric answer.
            elapsed: client-measured elapsed seconds (``>= 0``).

        Returns:
            An :class:`AnswerOutcome` (trial, post-trial mastery, progress).

        Raises:
            SessionNotFound:   if no such session exists.
            SessionExpired:    if the session has expired.
            NoPendingExercise: if no exercise is currently pending.
        """
        with self._lock_for(sid):
            agg = self._load(sid)
            if agg.pending is None:
                raise NoPendingExercise(sid)

            pending = agg.pending
            exercise = Exercise(a=pending.a, b=pending.b)
            config = agg.engine_state.config
            correct = (answer == pending.a + pending.b) and (
                elapsed < config.TIME_LIMIT
            )

            engine = PracticeEngine.from_state(
                agg.engine_state, rng=self._rng_factory()
            )
            result = engine.submit(exercise, correct, elapsed)

            now = self._clock.now()
            seq = agg.trial_seq + 1
            trial = TrialRecord(
                seq=seq,
                a=pending.a,
                b=pending.b,
                correct=correct,
                response_time=elapsed,
                s=result.s,
                E=result.E,
                theta_before=result.theta_before,
                theta_after=result.theta_after,
                created_at=now,
            )

            agg.engine_state = engine.snapshot()
            agg.trial_seq = seq
            agg.pending = None

            self._repo.add_trial(sid, trial)
            self._repo.save(agg)

            mastery = ExerciseMastery(
                a=pending.a,
                b=pending.b,
                streak=result.mastery.streak,
                faults=result.mastery.faults,
                mastered=result.mastery.mastered,
            )
            return AnswerOutcome(
                trial=trial,
                mastery=mastery,
                progress=self._progress_from_state(agg.engine_state),
            )

    def get_stats(self, sid: str) -> StatsResult:
        """Return aggregate progress plus the recent trial log for a session.

        Loads and slides the session (persisting the slide), then queries trial
        counts and the most recent trials.

        Args:
            sid: the session id.

        Returns:
            A :class:`StatsResult` bundling the aggregate, progress, totals, and
            the most recent trials (newest-first, capped at 20).

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
        """
        agg = self._load(sid, persist_slide=True)
        trials = self._repo.count_trials(sid)
        correct = self._repo.correct_count(sid)
        recent = self._repo.list_trials(sid, limit=20)
        return StatsResult(
            aggregate=agg,
            progress=self.progress(agg),
            trials=trials,
            correct=correct,
            recent=recent,
        )
