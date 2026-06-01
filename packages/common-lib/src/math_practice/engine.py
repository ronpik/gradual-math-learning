"""Practice engine orchestration (adaptive-practice-spec v1, "Engine").

The :class:`PracticeEngine` wires together the difficulty scorer, ability
tracker, selection policy and mastery tracker into a single facade that drives
one learner's session: it picks the next exercise, grades a submitted answer,
updates the latent ability, and tracks mastery progress.
"""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass

from .ability import AbilityTracker
from .config import EngineConfig
from .difficulty import (
    DifficultyScorer,
    LeveledDifficultyScorer,
    default_scorer_for,
)
from .mastery import MasteryState, MasteryTracker
from .models import Exercise
from .modules import curriculum_for
from .selection import SelectionPolicy
from .state import EngineState, ExerciseMastery


@dataclass
class TrialResult:
    """Outcome of a single graded trial (spec v1, "Engine").

    Bundles everything a caller (CLI/UI) needs to render feedback and the
    before/after ability so progress can be visualised.

    Attributes:
        exercise:      the exercise that was attempted.
        correct:       whether the learner's answer was correct.
        response_time: response time in seconds.
        s:             the graded trial score in ``[0, 1]``.
        E:             predicted success evaluated BEFORE the ability update.
        theta_before:  ability immediately before the update.
        theta_after:   ability immediately after the update.
        mastery:       the (mutated) mastery state for ``exercise``.
        level:         the structural difficulty level of ``exercise`` (``1..5``
                       for a leveled scorer, ``0`` when the scorer exposes no
                       ``level``).
    """

    exercise: Exercise
    correct: bool
    response_time: float
    s: float
    E: float
    theta_before: float
    theta_after: float
    mastery: MasteryState
    level: int


class PracticeEngine:
    """Single-learner adaptive practice session facade (spec v1, "Engine").

    Owns the full curriculum and the four collaborating components. The latent
    ability is mirrored on :attr:`theta` (kept in sync with the underlying
    :class:`~math_practice.ability.AbilityTracker`) for convenient inspection.
    """

    def __init__(
        self,
        config: EngineConfig | None = None,
        scorer: DifficultyScorer | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """Build the engine and seed the cold-start ability (spec v1).

        Args:
            config: engine hyper-parameters; defaults to :class:`EngineConfig`.
            scorer: difficulty scorer; defaults to the leveled scorer for
                ``config.op`` (via
                :func:`~math_practice.difficulty.default_scorer_for`).
            rng:    random source for selection; defaults to a fresh
                :class:`random.Random`.
        """
        self.config: EngineConfig = config if config is not None else EngineConfig()
        self._rng: random.Random = rng if rng is not None else random.Random()

        # Build the fixed curriculum pool once, op-aware and restricted to the
        # config's applicable levels (a module only contains the subset its range
        # permits, modules design §2); the shared cached list must not be mutated.
        self._exercises: list[Exercise] = curriculum_for(
            self.config.op,
            self.config.range_bound,
            self.config.applicable_levels,
        )

        # Default to the leveled scorer for this operation. A leveled scorer is
        # pool-aware, so fit it to the pool BEFORE it is used to precompute
        # difficulties (selection) or the cold-start b_min, otherwise delta is 0.
        self._scorer: DifficultyScorer = (
            scorer
            if scorer is not None
            else default_scorer_for(self.config)
        )
        if isinstance(self._scorer, LeveledDifficultyScorer):
            self._scorer.fit(self._exercises)

        # Collaborating components share the one config + exercise pool.
        self._ability = AbilityTracker(self.config)
        self._selection = SelectionPolicy(self.config, self._scorer, self._exercises)
        self._mastery = MasteryTracker(self.config, self._exercises)

        # Cold start: seed theta so the easiest item starts near p_start.
        b_min = min(self._scorer.score(ex) for ex in self._exercises)
        cold = AbilityTracker.cold_start_theta(b_min, self.config)
        self._ability.theta = cold
        self.theta: float = cold

        # Exercise to exclude from the very next draw (spec: exclude previous).
        self._last_shown: Exercise | None = None

    def next_exercise(self) -> Exercise:
        """Select the next exercise, excluding the immediately-previous one (spec v1).

        Returns:
            The chosen :class:`Exercise`. It is remembered so it is excluded
            from the following draw only.
        """
        exercise = self._selection.select(
            self.theta, exclude=self._last_shown, rng=self._rng
        )
        self._last_shown = exercise
        return exercise

    def submit(
        self, exercise: Exercise, correct: bool, response_time: float
    ) -> TrialResult:
        """Grade an answer, update ability and mastery, return the result (spec v1).

        The predicted success ``E`` and ``theta_before`` are captured before the
        ability update; ``theta_after`` after it. Mastery is recorded from
        correctness and response time (qualifying = correct and under the
        mastery time limit).

        Args:
            exercise:      the exercise that was attempted.
            correct:       whether the answer was correct.
            response_time: response time in seconds.

        Returns:
            A fully-populated :class:`TrialResult`.
        """
        b = self._scorer.score(exercise)
        s = self._ability.trial_score(correct, response_time)
        E = self._ability.expected_success(b)
        theta_before = self._ability.theta

        self._ability.update(b, s)
        theta_after = self._ability.theta
        self.theta = theta_after

        mastery = self._mastery.record(exercise, correct, response_time)

        return TrialResult(
            exercise=exercise,
            correct=correct,
            response_time=response_time,
            s=s,
            E=E,
            theta_before=theta_before,
            theta_after=theta_after,
            mastery=mastery,
            level=self._level_of(exercise),
        )

    def _level_of(self, exercise: Exercise) -> int:
        """Return the structural level of ``exercise`` (``0`` if unsupported).

        Delegates to the scorer's ``level`` method when it exposes one (every
        :class:`~math_practice.difficulty.LeveledDifficultyScorer` does); a
        scorer without levels (e.g.
        :class:`~math_practice.difficulty.AdditionFixedDifficultyScorer`) yields
        the sentinel ``0``.

        Args:
            exercise: the exercise whose level to look up.

        Returns:
            The structural difficulty level, or ``0`` when the scorer has none.
        """
        level = getattr(self._scorer, "level", None)
        return level(exercise) if callable(level) else 0

    def snapshot(self) -> EngineState:
        """Capture the full mutable engine state as an :class:`EngineState` (spec v1).

        The returned snapshot is self-contained: it holds a *copy* of the
        configuration, the latent ability, every exercise's mastery state, and
        the last-shown exercise as ``(a, b)``. It shares no mutable references
        with this engine, so later mutations here do not affect the snapshot.

        Returns:
            An :class:`EngineState` suitable for persistence and later
            reconstruction via :meth:`from_state`.
        """
        mastery = [
            ExerciseMastery(
                a=exercise.a,
                b=exercise.b,
                streak=state.streak,
                faults=state.faults,
                mastered=state.mastered,
            )
            for exercise, state in self._mastery.items()
        ]
        last_shown = (
            None
            if self._last_shown is None
            else (self._last_shown.a, self._last_shown.b)
        )
        return EngineState(
            theta=self.theta,
            config=dataclasses.replace(self.config),
            mastery=mastery,
            last_shown=last_shown,
        )

    @classmethod
    def from_state(
        cls, state: EngineState, rng: random.Random | None = None
    ) -> "PracticeEngine":
        """Rebuild a behaviourally identical engine from a snapshot (spec v1).

        Reconstructs the curriculum from ``state.config``, restores the latent
        ability, every exercise's mastery state, and the last-shown exercise.
        The resulting engine behaves exactly like a live one: ``next_exercise``
        excludes ``last_shown`` and ``submit`` continues updating the restored
        ability and mastery.

        Args:
            state: a previously captured :class:`EngineState`.
            rng:   random source for selection; defaults to a fresh
                :class:`random.Random`.

        Returns:
            A fully working :class:`PracticeEngine`.
        """
        engine = cls(config=state.config, rng=rng)

        # Restore the latent ability (both the tracker and the mirror).
        engine._ability.theta = state.theta
        engine.theta = state.theta

        # Restore mastery, keyed by exercise operands. The operator comes from
        # the restored config so subtraction keys match the rebuilt curriculum.
        op = state.config.op
        restored: dict[Exercise, MasteryState] = {
            Exercise(a=item.a, b=item.b, op=op): MasteryState(
                streak=item.streak,
                faults=item.faults,
                mastered=item.mastered,
            )
            for item in state.mastery
        }
        engine._mastery.load_states(restored)

        # Restore the exclusion target for the next draw.
        if state.last_shown is not None:
            a, b = state.last_shown
            engine._last_shown = Exercise(a=a, b=b, op=op)

        return engine

    def mastered_count(self) -> int:
        """Return the number of mastered exercises (delegates to the tracker)."""
        return self._mastery.mastered_count()

    def total(self) -> int:
        """Return the total number of curriculum exercises."""
        return self._mastery.total()

    def all_mastered(self) -> bool:
        """Return ``True`` when every curriculum exercise is mastered."""
        return self._mastery.all_mastered()

    def level_progress(self) -> dict[int, tuple[int, int]]:
        """Return per-level ``(mastered_count, total)`` over the pool.

        Buckets every curriculum exercise by its structural level (via the
        scorer's ``level`` lookup; ``0`` when the scorer has none) and counts how
        many in each bucket are currently mastered. Only levels with at least one
        exercise are included, so the keys are exactly the structural levels the
        module's range permits.

        Returns:
            A mapping from structural level to ``(mastered_count, total)``.
        """
        progress: dict[int, tuple[int, int]] = {}
        for exercise, state in self._mastery.items():
            lvl = self._level_of(exercise)
            mastered, total = progress.get(lvl, (0, 0))
            progress[lvl] = (mastered + (1 if state.mastered else 0), total + 1)
        return progress
