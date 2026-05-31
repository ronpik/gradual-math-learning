"""Engine configuration (adaptive-practice-spec v1).

All tunable parameters for difficulty scoring, ability tracking, item
selection, and mastery live here as a single immutable bundle so every
component shares one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    """Immutable bundle of engine hyper-parameters (spec v1).

    Attributes mirror the symbols used throughout the spec:

    Curriculum:
        MAX_SUM: largest allowed value of ``a + b`` in the curriculum.

    Difficulty (b):
        w_mag:    weight on ``max(a, b)`` (magnitude term).
        w_order:  weight on the ``a < b`` ordering indicator.
        w_double: penalty subtracted when ``a == b`` (doubles are easier).

    Time / trial score (s):
        TIME_LIMIT:          response time (s) at/above which the trial scores 0.
        tau_time:            time constant in the time-weight logistic.
        p_time:              exponent in the time-weight logistic.
        slow_correct_credit: floor credit for a correct-but-slow answer.

    Ability (Elo / 1-PL):
        K:                Elo learning rate.
        difficulty_scale: tau_diff, the logistic temperature over (b - theta).
        p_target:         target predicted success used by selection.
        p_start:          assumed success probability at cold start.

    Selection:
        selection_temperature: tau_sel, temperature of the selection softmax.
        epsilon:               additive floor on selection weights.

    Mastery:
        mastery_streak:     qualifying-trial streak required to master.
        mastery_time_limit: max response time (s, exclusive) for a correct
                            trial to qualify toward mastery.
        max_faults:         non-qualifying trials tolerated before reset.
    """

    MAX_SUM: int = 10
    w_mag: float = 1.0
    w_order: float = 0.5
    w_double: float = 0.75
    TIME_LIMIT: float = 90.0
    tau_time: float = 12.0
    p_time: float = 1.0
    slow_correct_credit: float = 0.85  # = floor
    K: float = 0.5
    difficulty_scale: float = 2.0  # tau_diff
    p_target: float = 0.85
    p_start: float = 0.90
    selection_temperature: float = 0.10  # tau_sel
    epsilon: float = 1e-3
    mastery_streak: int = 3
    mastery_time_limit: float = 10.0
    max_faults: int = 2
