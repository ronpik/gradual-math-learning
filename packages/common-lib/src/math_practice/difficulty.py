"""Difficulty scoring for exercises (adaptive-practice-spec v1).

Difficulty ``b`` summarises how hard a fact is, feeding both the ability
update (as the item difficulty in the Elo / 1-PL model) and item selection.

Spec formula (Difficulty section):

    b(a, b) = w_mag * max(a, b)
              + w_order * 1[a < b]
              - w_double * 1[a == b]

The ordering term reflects that ``1 + 2`` is marginally harder than ``2 + 1``
for early learners (counting on from the larger addend), while doubles such as
``5 + 5`` are easier and so receive a discount.
"""

from __future__ import annotations

import abc

from .config import EngineConfig
from .models import Exercise


class DifficultyScorer(abc.ABC):
    """Abstract difficulty scorer (spec v1, Difficulty section).

    Implementations map an :class:`Exercise` to a real-valued difficulty
    ``b``. The value is consumed by the ability tracker (as item difficulty)
    and by the selection policy (to predict success).
    """

    @abc.abstractmethod
    def score(self, exercise: Exercise) -> float:
        """Return the difficulty ``b`` of ``exercise``.

        Args:
            exercise: the exercise to score.

        Returns:
            The scalar difficulty value.
        """
        raise NotImplementedError


class AdditionFixedDifficultyScorer(DifficultyScorer):
    """Closed-form difficulty for addition facts (spec v1, Difficulty section).

    Computes ``b = w_mag*max(a, b) + w_order*1[a<b] - w_double*1[a==b]`` using
    the weights bundled in :class:`~math_practice.config.EngineConfig`.

    With the default config this reproduces the sample table::

        1 + 1 -> 0.25    2 + 1 -> 2.00    1 + 2 -> 2.50
        5 + 5 -> 4.25    7 + 2 -> 7.00    2 + 7 -> 7.50
    """

    def __init__(self, config: EngineConfig = EngineConfig()) -> None:
        """Store the config supplying the difficulty weights.

        Args:
            config: engine configuration providing ``w_mag``, ``w_order`` and
                ``w_double``. Defaults to a fresh :class:`EngineConfig`.
        """
        self._config = config

    def score(self, exercise: Exercise) -> float:
        """Return the difficulty ``b`` of ``exercise`` (spec v1).

        Args:
            exercise: the addition exercise to score.

        Returns:
            ``w_mag*max(a, b) + w_order*1[a<b] - w_double*1[a==b]``.
        """
        cfg = self._config
        a, b = exercise.a, exercise.b
        difficulty = cfg.w_mag * max(a, b)
        if a < b:
            difficulty += cfg.w_order
        if a == b:
            difficulty -= cfg.w_double
        return difficulty
