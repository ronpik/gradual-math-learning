"""Adaptive item selection (adaptive-practice-spec v1, "Selection").

Picks the next exercise to present so the learner's *predicted* success on it
sits near :attr:`EngineConfig.p_target`. Items whose predicted success is close
to the target receive the highest sampling weight; nothing is ever removed from
the pool, so already-seen (and even mastered) items remain eligible.
"""

from __future__ import annotations

import math
import random

from .config import EngineConfig
from .difficulty import DifficultyScorer
from .models import Exercise

# Shared default RNG used when a caller does not supply one. Module-level so
# repeated selections stay reproducible within a process while remaining
# overridable per call.
_DEFAULT_RNG = random.Random()


class SelectionPolicy:
    """Weighted sampler over the exercise pool (spec v1, "Selection").

    For each item ``i`` the policy computes the predicted success ``E_i`` at the
    current ability ``theta`` and assigns a weight::

        E_i      = 1 / (1 + exp((b_i - theta) / tau_diff))
        weight_i = exp(-|E_i - p_target| / tau_sel) + epsilon

    The next item is sampled proportional to ``weight_i``. Item difficulties
    ``b_i`` are precomputed once at construction via the supplied scorer.
    """

    def __init__(
        self,
        config: EngineConfig,
        scorer: DifficultyScorer,
        exercises: list[Exercise],
    ) -> None:
        """Precompute difficulty ``b`` for every exercise.

        Args:
            config:    engine hyper-parameters (``tau_diff``, ``p_target``,
                       ``tau_sel``, ``epsilon``).
            scorer:    difficulty scorer used to assign each item its ``b``.
            exercises: the full, fixed pool to select from.
        """
        self._config = config
        self._exercises: list[Exercise] = list(exercises)
        # Precompute b_i for every item (spec: difficulty is static per item).
        self._difficulties: list[float] = [
            scorer.score(exercise) for exercise in self._exercises
        ]

    def _expected_success(self, b: float, theta: float) -> float:
        """Logistic predicted success ``E`` for difficulty ``b`` at ``theta``."""
        tau_diff = self._config.difficulty_scale
        return 1.0 / (1.0 + math.exp((b - theta) / tau_diff))

    def weight_for(self, E: float) -> float:
        """Selection weight for a predicted success ``E`` (spec v1).

        ``weight = exp(-|E - p_target| / tau_sel) + epsilon``. The ``epsilon``
        floor keeps every item reachable even when far from the target.
        """
        cfg = self._config
        return (
            math.exp(-abs(E - cfg.p_target) / cfg.selection_temperature)
            + cfg.epsilon
        )

    def select(
        self,
        theta: float,
        exclude: Exercise | None = None,
        rng: random.Random | None = None,
    ) -> Exercise:
        """Sample the next exercise proportional to its selection weight (spec v1).

        Args:
            theta:   current ability estimate used to compute each ``E_i``.
            exclude: an exercise to omit from *this* draw only (typically the
                     immediately-previous item). It stays in the pool for
                     future draws.
            rng:     random source; defaults to a shared module-level RNG.

        Returns:
            The chosen :class:`Exercise`.

        Raises:
            ValueError: if no candidate exercises remain after exclusion.
        """
        if rng is None:
            rng = _DEFAULT_RNG

        candidates: list[Exercise] = []
        weights: list[float] = []
        for exercise, b in zip(self._exercises, self._difficulties):
            if exclude is not None and exercise == exclude:
                continue
            E = self._expected_success(b, theta)
            candidates.append(exercise)
            weights.append(self.weight_for(E))

        if not candidates:
            raise ValueError("no candidate exercises available for selection")

        # weights are strictly positive (epsilon floor), so this is safe.
        return rng.choices(candidates, weights=weights, k=1)[0]
