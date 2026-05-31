"""Snapshot/restore seam for the practice engine (adaptive-practice-spec v1).

Provides plain-dataclass value objects that capture the *entire* mutable state
of a :class:`~math_practice.engine.PracticeEngine` — latent ability, a copy of
the configuration, every exercise's mastery bookkeeping, and the last-shown
exercise — so a session can be persisted and later rebuilt into a behaviourally
identical engine.

These dataclasses carry data only: they hold no references to the live engine
and have no behaviour, which keeps the persistence boundary clean.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EngineConfig


@dataclass
class ExerciseMastery:
    """Serialisable mastery bookkeeping for a single exercise (spec v1).

    Mirrors :class:`~math_practice.mastery.MasteryState` but is keyed by the
    exercise operands so it can be persisted independently of the live
    curriculum objects.

    Attributes:
        a:        first operand of the exercise.
        b:        second operand of the exercise.
        streak:   number of consecutive qualifying trials currently counted.
        faults:   non-qualifying trials accumulated since the last reset.
        mastered: latched flag, ``True`` once the streak target was met.
    """

    a: int
    b: int
    streak: int
    faults: int
    mastered: bool


@dataclass
class EngineState:
    """Complete, restorable snapshot of a :class:`PracticeEngine` (spec v1).

    Captures everything needed to rebuild a behaviourally identical engine via
    :meth:`PracticeEngine.from_state`.

    Attributes:
        theta:      the latent ability at snapshot time.
        config:     a copy of the engine's :class:`EngineConfig`.
        mastery:    per-exercise mastery state for the full curriculum.
        last_shown: ``(a, b)`` of the most recently drawn exercise (excluded
                    from the next draw), or ``None`` if none has been drawn.
    """

    theta: float
    config: EngineConfig
    mastery: list[ExerciseMastery]
    last_shown: tuple[int, int] | None
