"""Session orchestration service (the application/use-case layer).

:class:`SessionService` is the single seam between the HTTP layer and the
persistence + engine layers. It owns the session lifecycle:

    * **create** — resolve a module to an :class:`~math_practice.EngineConfig`,
      seed the engine from the learner's resumable
      :class:`~math_practice_backend.domain.ModuleProgress` (or cold-start), and
      persist a new :class:`~math_practice_backend.domain.SessionAggregate` for the
      chosen ``(module, mode)``.
    * **load + slide** — every session-scoped operation loads the aggregate,
      enforces the sliding-TTL expiry, and refreshes ``last_activity_at`` /
      ``expires_at``.
    * **next** — honour the mode's stop rule, then draw (or re-show) the pending
      exercise.
    * **answer** — honour the mode's late-answer rule, grade op-aware against the
      server-known result, update the engine, write progress through to
      :class:`ModuleProgress`, and dual-log a :class:`TrialRecord` (engine trace)
      and a :class:`SessionExercise` (clean audit row).
    * **summary** — the run's headline metric, personal best, and per-level
      mastery; **stats** — the student-safe aggregate projection.

A **mode** never changes which exercise the engine selects next (selection is
always the 85%-comfort softmax); it contributes only a server-enforced stop rule
and a headline metric, resolved once via :func:`~math_practice_backend.modes.get_mode`
so the service never branches on a mode string.

Everything crossing this boundary is a dataclass; Pydantic lives only at the
HTTP edge. Mutating operations are guarded by a per-session lock so concurrent
``next``/``answer`` calls on one session are serialised.
"""

from __future__ import annotations

import dataclasses
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
    get_module,
)

from .clock import Clock
from .domain import (
    ModuleProgress,
    PendingExercise,
    SessionAggregate,
    SessionExercise,
    TrialRecord,
)
from .enums import Mode, SessionStatus
from .errors import (
    InvalidConfig,
    ModuleNotFound,
    NoPendingExercise,
    SessionComplete,
    SessionExpired,
    SessionNotFound,
)
from .modes import get_mode
from .repositories import LearnerRepository, SessionRepository


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


class LevelProgress(NamedTuple):
    """Per-level completion projection (student-safe; no engine internals).

    Attributes:
        level:    the structural difficulty level (1..5).
        mastered: number of mastered exercises within the level.
        total:    total number of exercises within the level.
    """

    level: int
    mastered: int
    total: int


class AnswerOutcome(NamedTuple):
    """Result bundle returned by :meth:`SessionService.submit_answer`.

    Attributes:
        trial:    the persisted :class:`TrialRecord`.
        mastery:  the post-trial mastery state for the answered exercise.
        progress: session progress after applying the trial.
        finished: whether the mode's stop rule is now met (the run is over).
        remaining: the mode's small "what is left" payload (``questions_left`` /
                  ``seconds_left`` / empty), suitable for the student surface.
    """

    trial: TrialRecord
    mastery: ExerciseMastery
    progress: Progress
    finished: bool
    remaining: dict


class SummaryResult(NamedTuple):
    """End-of-run summary projection returned by :meth:`SessionService.get_summary`.

    Carries only derived, student-safe signals — the mode's headline metric, the
    personal best and whether this run beat it, and per-level mastery counts. No
    engine internals (θ, ``s``, ``E``) cross this boundary.

    Attributes:
        module_id:      the module practiced (e.g. ``"sub_20"``).
        label:          the module's display label.
        mode:           the practice mode.
        status:         the session's lifecycle status.
        questions_done: number of answered questions.
        correct_count:  number of correct answers.
        accuracy:       ``correct_count / questions_done`` (0 when none).
        total_time:     summed answer time in seconds.
        avg_time:       mean answer time per question (0 when none).
        headline:       the mode's headline-metric payload.
        best:           the personal best over completed sessions (mode-specific),
                        or ``None`` when the mode has no best / none exists yet.
        is_new_best:    whether this run set a new personal best.
        level_progress: per-level mastery counts, ordered by level.
    """

    module_id: str
    label: str
    mode: Mode
    status: SessionStatus
    questions_done: int
    correct_count: int
    accuracy: float
    total_time: float
    avg_time: float
    headline: dict
    best: float | int | None
    is_new_best: bool
    level_progress: list[LevelProgress]


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


class StudentStats(NamedTuple):
    """Student-safe aggregate statistics projection for a play session.

    All engine internals (theta, mastery counts, per-trial scores) are excluded;
    only the surface metrics the learner-facing UI needs are carried.

    Attributes:
        questions_done:            total number of recorded trials.
        correct:                   number of correct trials.
        accuracy:                  ``correct / questions_done`` (0 when none).
        total_time_seconds:        summed response time over all trials.
        avg_time_seconds:          mean response time per trial (0 when none).
        module_completion_percent: percent of curriculum exercises mastered.
        streak:                    consecutive correct answers ending at the most
                                   recent trial.
    """

    questions_done: int
    correct: int
    accuracy: float
    total_time_seconds: float
    avg_time_seconds: float
    module_completion_percent: float
    streak: int


class SessionService:
    """Use-case orchestration for practice sessions.

    Wires a :class:`~math_practice_backend.repositories.SessionRepository`, a
    :class:`~math_practice_backend.repositories.LearnerRepository`, a
    :class:`~math_practice_backend.clock.Clock`, a sliding TTL, and an RNG factory
    into the session lifecycle. The session repository owns the ephemeral 24h
    aggregate (plus its trial and audit logs); the learner repository owns the
    permanent learner identity and the resumable per-(learner, module) progress
    the service seeds from and writes through on every answer. The service is
    stateless except for a lazily-built table of per-session locks; all durable
    state lives in the repositories.
    """

    def __init__(
        self,
        repo: SessionRepository,
        learner_repo: LearnerRepository,
        clock: Clock,
        ttl: timedelta,
        rng_factory: Callable[[], random.Random] = lambda: random.Random(),
    ) -> None:
        """Build the service.

        Args:
            repo:         the session persistence boundary (ephemeral aggregate +
                logs).
            learner_repo: the learner/module-progress persistence boundary
                (permanent identity + resumable progress).
            clock:        source of aware-UTC "now".
            ttl:          sliding retention window; ``expires_at = now + ttl``.
            rng_factory:  factory producing a fresh :class:`random.Random` for
                each engine rehydration (kept injectable for determinism).
        """
        self._repo = repo
        self._learner_repo = learner_repo
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

    # ----- student-safe projections -----------------------------------------

    @staticmethod
    def module_completion_percent(agg: SessionAggregate) -> float:
        """Percent of curriculum exercises mastered for a session.

        Derived from :meth:`progress`: ``mastered_count / total * 100``. Returns
        ``0.0`` when the curriculum is empty (``total == 0``).

        Args:
            agg: the session aggregate.

        Returns:
            The completion percentage in ``[0.0, 100.0]``.
        """
        p = SessionService.progress(agg)
        if p.total == 0:
            return 0.0
        return p.mastered_count / p.total * 100.0

    def current_streak(self, sid: str) -> int:
        """Count consecutive correct answers ending at the most recent trial.

        Walks the trial log newest-first and counts how many leading trials are
        correct, stopping at the first wrong answer. Returns ``0`` when the most
        recent trial is wrong or there are no trials.

        Args:
            sid: the session id.

        Returns:
            The current correct-answer streak.
        """
        streak = 0
        for trial in self._repo.list_trials(sid):
            if not trial.correct:
                break
            streak += 1
        return streak

    def get_student_stats(self, sid: str) -> StudentStats:
        """Return the student-safe aggregate statistics for a session.

        Loads and slides the session (persisting the slide), then computes the
        learner-facing surface metrics without leaking any engine internals.

        Args:
            sid: the session id.

        Returns:
            A :class:`StudentStats` projection.

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
        """
        agg = self._load(sid, persist_slide=True)
        done = self._repo.count_trials(sid)
        correct = self._repo.correct_count(sid)
        total_time = self._repo.sum_response_time(sid)
        accuracy = (correct / done) if done > 0 else 0.0
        avg_time = (total_time / done) if done > 0 else 0.0
        return StudentStats(
            questions_done=done,
            correct=correct,
            accuracy=accuracy,
            total_time_seconds=total_time,
            avg_time_seconds=avg_time,
            module_completion_percent=self.module_completion_percent(agg),
            streak=self.current_streak(sid),
        )

    # ----- config building --------------------------------------------------

    @staticmethod
    def build_module_config(
        module_id: str, overrides: dict | None
    ) -> EngineConfig:
        """Resolve a module to an :class:`EngineConfig`, applying any overrides.

        The base config is built from the module spec (its op, range, and
        per-module time/mastery knobs); ``overrides`` then patch individual
        :class:`EngineConfig` fields. Override validation mirrors the field
        annotations: ``int`` fields accept ints, ``float`` fields accept numbers
        (coerced to float), ``str`` fields (e.g. ``op``) accept strings;
        ``applicable_levels`` is structural and may not be overridden. The
        resolved config must keep ``range_bound >= 2``.

        Args:
            module_id: the module to resolve (e.g. ``"sub_20"``).
            overrides: optional partial mapping of ``EngineConfig`` field names to
                values.

        Returns:
            The constructed (frozen) :class:`EngineConfig`.

        Raises:
            ModuleNotFound: if ``module_id`` is not in the module registry.
            InvalidConfig:  on unknown / disallowed keys or invalid values, or if
                the resolved ``range_bound`` is below 2.
        """
        try:
            spec = get_module(module_id)
        except ValueError as exc:
            raise ModuleNotFound(module_id) from exc

        base = spec.build_config()
        if not overrides:
            return base

        field_types = {f.name: f.type for f in fields(EngineConfig)}
        unknown = sorted(set(overrides) - set(field_types))
        if unknown:
            raise InvalidConfig(f"Unknown config field(s): {', '.join(unknown)}")
        if "applicable_levels" in overrides:
            raise InvalidConfig(
                "Config field 'applicable_levels' cannot be overridden"
            )

        coerced: dict = {}
        for name, value in overrides.items():
            expected = field_types[name]
            # Field annotations are simple strings; coerce numerics so an int
            # passed for a float field is accepted, accept strings for str
            # fields (e.g. ``op``), and reject the rest.
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
            elif expected == "str":
                if not isinstance(value, str):
                    raise InvalidConfig(
                        f"Config field {name!r} expects a string, got "
                        f"{type(value).__name__}"
                    )
                coerced[name] = value
            else:
                coerced[name] = value

        try:
            config = dataclasses.replace(base, **coerced)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise InvalidConfig(f"Invalid config overrides: {exc}") from exc

        if config.range_bound < 2:
            raise InvalidConfig("Config field 'range_bound' must be >= 2")
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

    def create_session(
        self,
        learner_id: str | None,
        module_id: str,
        mode: Mode,
        overrides: dict | None = None,
    ) -> SessionAggregate:
        """Create and persist a brand-new practice run for a ``(module, mode)``.

        Resolves (or mints) the learner, builds the module's
        :class:`EngineConfig`, and seeds a fresh
        :class:`~math_practice.PracticeEngine` from the learner's resumable
        :class:`ModuleProgress` for that module if present (so θ + mastery carry
        over), else cold-starts. The engine snapshot, the mode's stop-rule targets
        (``target_count`` / ``target_seconds``), and ``started_at == created_at``
        (so a timed mode's deadline is known at creation) are recorded on a new
        ``ACTIVE`` aggregate with a uuid4-hex id.

        Args:
            learner_id: the owning learner's id, or ``None`` to mint a new one.
            module_id:  the module to practice (e.g. ``"add_20"``).
            mode:       the practice mode (stop rule + headline metric).
            overrides:  optional partial ``EngineConfig`` field overrides.

        Returns:
            The newly created :class:`SessionAggregate`.

        Raises:
            ModuleNotFound: if ``module_id`` is not in the module registry.
            InvalidConfig:  if any override is unknown or invalid.
            UnknownMode:    if ``mode`` is not a registered practice mode.
        """
        now = self._clock.now()
        learner = self._learner_repo.get_or_create(learner_id, now)
        config = self.build_module_config(module_id, overrides)

        progress = self._learner_repo.get_progress(learner.id, module_id)
        if progress is not None:
            state = EngineState(
                theta=progress.theta,
                config=config,
                mastery=progress.mastery,
                last_shown=None,
            )
            engine = PracticeEngine.from_state(state, rng=self._rng_factory())
        else:
            engine = PracticeEngine(config=config, rng=self._rng_factory())

        mode_strategy = get_mode(mode)
        agg = SessionAggregate(
            id=uuid.uuid4().hex,
            learner_id=learner.id,
            module_id=module_id,
            mode=mode,
            status=SessionStatus.ACTIVE,
            created_at=now,
            started_at=now,
            ended_at=None,
            last_activity_at=now,
            expires_at=now + self._ttl,
            target_count=mode_strategy.target_count(),
            target_seconds=mode_strategy.target_seconds(),
            engine_state=engine.snapshot(),
            pending=None,
            trial_seq=0,
            questions_done=0,
            correct_count=0,
            total_time=0.0,
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

        Guarded by the per-session lock. A completed session is immutable and
        raises :class:`SessionComplete`. Otherwise the mode's stop rule is
        evaluated: if already met the session is marked ``COMPLETED`` (with
        ``ended_at``), persisted, and :class:`SessionComplete` is raised. If a
        pending exercise already exists it is returned unchanged (resume
        re-show). Otherwise the engine is rehydrated, a new exercise is drawn,
        recorded as the pending exercise (carrying the engine's op so the client
        can render it), and the updated engine snapshot (capturing
        ``last_shown``) is persisted.

        Args:
            sid: the session id.

        Returns:
            The pending :class:`PendingExercise`.

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
            SessionComplete: if the session has already met its stop rule.
        """
        with self._lock_for(sid):
            agg = self._load(sid)
            if agg.status is SessionStatus.COMPLETED:
                raise SessionComplete(sid)

            mode = get_mode(agg.mode)
            now = self._clock.now()
            if mode.is_complete(agg, now):
                agg.status = SessionStatus.COMPLETED
                agg.ended_at = now
                self._repo.save(agg)
                raise SessionComplete(sid)

            if agg.pending is not None:
                self._repo.save(agg)  # persist the activity slide
                return agg.pending

            engine = PracticeEngine.from_state(
                agg.engine_state, rng=self._rng_factory()
            )
            exercise = engine.next_exercise()
            pending = PendingExercise(
                a=exercise.a,
                b=exercise.b,
                issued_at=now,
                op=agg.engine_state.config.op,
            )
            agg.pending = pending
            agg.engine_state = engine.snapshot()
            self._repo.save(agg)
            return pending

    def submit_answer(
        self, sid: str, answer: int, elapsed: float
    ) -> AnswerOutcome:
        """Grade an answer op-aware, update progress, and dual-log the trial.

        Guarded by the per-session lock. A completed session is immutable and
        raises :class:`SessionComplete`; a pending exercise is required
        (otherwise :class:`NoPendingExercise`). The mode's late-answer rule is
        checked first: an answer the mode rejects (e.g. arriving at or past the
        3-minute deadline) closes the session ``COMPLETED`` and raises
        :class:`SessionComplete` without recording the trial.

        Correctness is graded server-side and op-aware: ``expected = a + b`` for
        ``"+"`` and ``a - b`` for ``"-"``; ``correct`` requires ``answer ==
        expected`` *and* ``elapsed < config.TIME_LIMIT``. The engine is rehydrated
        and asked to grade the trial; the result feeds both an engine-trace
        :class:`TrialRecord` and a clean :class:`SessionExercise` audit row. The
        denormalized metrics, engine snapshot, and bumped ``trial_seq`` are
        updated and the pending exercise cleared. Progress is **written through**
        to :class:`ModuleProgress` so it survives an abandoned session, and the
        mode's stop rule is re-evaluated to set ``COMPLETED`` when this answer
        ends the run.

        Args:
            sid:     the session id.
            answer:  the learner's numeric answer.
            elapsed: client-measured elapsed seconds (``>= 0``).

        Returns:
            An :class:`AnswerOutcome` (trial, post-trial mastery, progress,
            whether the run is finished, and the mode's ``remaining`` payload).

        Raises:
            SessionNotFound:   if no such session exists.
            SessionExpired:    if the session has expired.
            SessionComplete:   if the session is already complete or the answer
                arrived too late for a timed mode.
            NoPendingExercise: if no exercise is currently pending.
        """
        with self._lock_for(sid):
            agg = self._load(sid)
            if agg.status is SessionStatus.COMPLETED:
                raise SessionComplete(sid)
            if agg.pending is None:
                raise NoPendingExercise(sid)

            mode = get_mode(agg.mode)
            now = self._clock.now()
            if not mode.accepts_answer(agg, now):
                agg.status = SessionStatus.COMPLETED
                agg.ended_at = now
                self._repo.save(agg)
                raise SessionComplete(sid)

            pending = agg.pending
            config = agg.engine_state.config
            op = config.op
            expected = (
                pending.a + pending.b if op == "+" else pending.a - pending.b
            )
            correct = (answer == expected) and (elapsed < config.TIME_LIMIT)

            exercise = Exercise(a=pending.a, b=pending.b, op=op)
            engine = PracticeEngine.from_state(
                agg.engine_state, rng=self._rng_factory()
            )
            result = engine.submit(exercise, correct, elapsed)

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
            audit = SessionExercise(
                seq=seq,
                a=pending.a,
                b=pending.b,
                op=op,
                level=result.level,
                given_answer=answer,
                correct=correct,
                elapsed=elapsed,
                created_at=now,
            )

            agg.engine_state = engine.snapshot()
            agg.trial_seq = seq
            agg.pending = None
            agg.questions_done += 1
            agg.correct_count += int(correct)
            agg.total_time += elapsed

            # Write-through: persist θ + mastery so progress survives an
            # abandoned session and seeds the next run for this (learner, module).
            self._learner_repo.save_progress(
                ModuleProgress(
                    learner_id=agg.learner_id,
                    module_id=agg.module_id,
                    theta=agg.engine_state.theta,
                    mastery=agg.engine_state.mastery,
                    updated_at=now,
                )
            )

            finished = mode.is_complete(agg, now)
            if finished:
                agg.status = SessionStatus.COMPLETED
                agg.ended_at = now

            self._repo.add_trial(sid, trial)
            self._repo.add_session_exercise(sid, audit)
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
                finished=finished,
                remaining=mode.remaining(agg, now),
            )

    def get_summary(self, sid: str) -> SummaryResult:
        """Return the run's student-safe end-of-run summary.

        Loads and slides the session (persisting the slide), rehydrates an engine
        from the snapshot purely to read per-level mastery, and compares the run's
        headline against the learner's personal best for this
        ``(module, mode)``. The "new best" comparison is mode-aware: smaller is
        better for the time-based Fastest-20 best, larger for the count-based
        3-minute best; Endless has no best so ``is_new_best`` is always ``False``.

        Args:
            sid: the session id.

        Returns:
            A :class:`SummaryResult` (headline, personal best, per-level mastery).

        Raises:
            SessionNotFound: if no such session exists.
            SessionExpired:  if the session has expired.
        """
        agg = self._load(sid, persist_slide=True)
        mode = get_mode(agg.mode)

        engine = PracticeEngine.from_state(
            agg.engine_state, rng=self._rng_factory()
        )
        level_progress = [
            LevelProgress(level=level, mastered=mastered, total=total)
            for level, (mastered, total) in sorted(
                engine.level_progress().items()
            )
        ]

        done = agg.questions_done
        accuracy = (agg.correct_count / done) if done > 0 else 0.0
        avg_time = (agg.total_time / done) if done > 0 else 0.0

        best = self._repo.best_result(agg.learner_id, agg.module_id, agg.mode)
        headline = mode.headline(agg)
        is_new_best = self._is_new_best(agg.mode, headline, best)

        return SummaryResult(
            module_id=agg.module_id,
            label=get_module(agg.module_id).label,
            mode=agg.mode,
            status=agg.status,
            questions_done=done,
            correct_count=agg.correct_count,
            accuracy=accuracy,
            total_time=agg.total_time,
            avg_time=avg_time,
            headline=headline,
            best=best,
            is_new_best=is_new_best,
            level_progress=level_progress,
        )

    @staticmethod
    def _is_new_best(
        mode: Mode, headline: dict, best: float | int | None
    ) -> bool:
        """Compare a run's headline against the personal best for its mode.

        Fastest-20 is time-based (lower is better); 3-minute is count-based
        (higher is better); Endless has no best. A ``None`` best (no prior
        qualifying session, or a mode without a best) means this run is the best
        only for the modes that *have* one.

        Args:
            mode:     the practice mode.
            headline: the run's headline-metric payload.
            best:     the personal best over prior completed sessions, if any.

        Returns:
            ``True`` when this run set a new personal best.
        """
        if mode is Mode.FASTEST_20:
            value = headline.get("total_time_seconds")
            if value is None:
                return False
            return best is None or value < best
        if mode is Mode.THREE_MINUTE:
            value = headline.get("questions_done")
            if value is None:
                return False
            return best is None or value > best
        return False

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
