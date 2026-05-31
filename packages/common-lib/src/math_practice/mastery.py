"""Per-exercise mastery tracking (adaptive-practice-spec v1, "Mastery").

Implements the *forgiving-streak* mastery rule. Each exercise accumulates a
streak of qualifying trials; a small number of non-qualifying trials are
tolerated, but exceeding the tolerance resets the streak. Once the streak
reaches the configured length the exercise is permanently (latched) mastered.

Mastery is progress/UI signal only: it never affects which exercise is
selected next.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EngineConfig
from .models import Exercise


@dataclass
class MasteryState:
    """Mutable mastery bookkeeping for a single exercise (spec v1, "Mastery").

    Attributes:
        streak:   number of consecutive qualifying trials currently counted.
        faults:   non-qualifying trials accumulated since the last reset.
        mastered: latched flag, set ``True`` once the streak target is met and
                  never cleared thereafter.
    """

    streak: int = 0
    faults: int = 0
    mastered: bool = False


class MasteryTracker:
    """Tracks the forgiving-streak mastery state of every curriculum item.

    For each exercise a trial is *qualifying* when it is correct AND answered
    in under ``config.mastery_time_limit`` seconds (a correct-but-slow answer
    does not count toward mastery).

        - qualifying trial:     ``streak += 1``
        - non-qualifying trial: ``faults += 1``; if ``faults > max_faults`` then
          ``streak = 0`` and ``faults = 0`` (the streak is forgiven up to the
          fault tolerance, then reset).
        - an exercise becomes ``mastered`` (latched) once ``streak >=
          mastery_streak``.

    Mastery is a progress/UI concern only and never influences selection.
    """

    def __init__(self, config: EngineConfig, exercises: list[Exercise]) -> None:
        """Initialise a fresh :class:`MasteryState` for each exercise.

        Args:
            config:    engine configuration supplying the mastery thresholds.
            exercises: the full curriculum pool to track.
        """
        self._config = config
        self._states: dict[Exercise, MasteryState] = {
            exercise: MasteryState() for exercise in exercises
        }

    def record(
        self, exercise: Exercise, correct: bool, response_time: float
    ) -> MasteryState:
        """Record a trial outcome and return the updated state (spec v1).

        Applies the forgiving-streak rule described on the class. Once an
        exercise is mastered the flag is latched and never cleared, though the
        streak/fault counters continue to update.

        Args:
            exercise:      the exercise that was attempted.
            correct:       whether the answer was correct.
            response_time: response time in seconds; a trial qualifies only when
                           it is correct AND under ``mastery_time_limit``.

        Returns:
            The (mutated) :class:`MasteryState` for ``exercise``.
        """
        state = self._states[exercise]
        qualifying = correct and response_time < self._config.mastery_time_limit

        if qualifying:
            state.streak += 1
        else:
            state.faults += 1
            if state.faults > self._config.max_faults:
                state.streak = 0
                state.faults = 0

        if state.streak >= self._config.mastery_streak:
            state.mastered = True

        return state

    def load_states(self, states: dict[Exercise, MasteryState]) -> None:
        """Overwrite tracked mastery states from a saved mapping (spec v1, restore).

        Used by :meth:`math_practice.engine.PracticeEngine.from_state` to rebuild
        a tracker from a persisted snapshot. Only exercises present in both the
        current curriculum and ``states`` are updated; the existing fresh state
        is kept for any exercise not mentioned in ``states``.

        Args:
            states: mapping from :class:`Exercise` to the mastery state to apply.
        """
        for exercise, state in states.items():
            if exercise in self._states:
                self._states[exercise] = state

    def items(self) -> list[tuple[Exercise, MasteryState]]:
        """Return ``(exercise, state)`` pairs for every tracked exercise.

        The order follows the curriculum order the tracker was built with.
        Used by :meth:`math_practice.engine.PracticeEngine.snapshot`.
        """
        return list(self._states.items())

    def state(self, exercise: Exercise) -> MasteryState:
        """Return the current :class:`MasteryState` for ``exercise``."""
        return self._states[exercise]

    def mastered_count(self) -> int:
        """Return the number of exercises currently mastered."""
        return sum(1 for state in self._states.values() if state.mastered)

    def total(self) -> int:
        """Return the total number of tracked exercises."""
        return len(self._states)

    def all_mastered(self) -> bool:
        """Return ``True`` when every tracked exercise is mastered."""
        return all(state.mastered for state in self._states.values())
