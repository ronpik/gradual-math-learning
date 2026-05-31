"""Ability tracking via Elo / 1-PL update (adaptive-practice-spec v1).

The :class:`AbilityTracker` owns the learner's latent ability ``theta`` and
the machinery that turns a single trial (correctness + response time) into a
graded score ``s`` and an Elo-style ability update.
"""

from __future__ import annotations

import math

from .config import EngineConfig


class AbilityTracker:
    """Track and update the learner's latent ability ``theta`` (spec v1).

    Combines three spec components:

    * **Time weight** ``w(t)`` -- a logistic decay over response time.
    * **Trial score** ``s`` -- graded credit in ``[0, 1]`` for a trial.
    * **Ability update** -- an Elo / 1-PL step on ``theta``.

    Attributes:
        config: the shared :class:`EngineConfig` bundle.
        theta:  the current latent ability estimate (public, mutable).
    """

    def __init__(self, config: EngineConfig, theta: float | None = None) -> None:
        """Create a tracker.

        Args:
            config: engine hyper-parameters.
            theta:  initial ability. If ``None`` the attribute is set to
                ``0.0`` and the caller is expected to seed it via
                :meth:`cold_start_theta` (spec: cold start).
        """
        self.config = config
        self.theta: float = 0.0 if theta is None else theta

    def time_weight(self, t: float) -> float:
        """Compute the time weight ``w(t)`` (spec: time weight).

        ``w(t) = 1 / (1 + (t / tau_time) ** p_time)`` for ``0 < t < TIME_LIMIT``.

        Boundaries:
            * ``t <= 0`` is treated as instantaneous: ``w = 1.0``.
            * ``t >= TIME_LIMIT`` scores no time credit: ``w = 0.0``.

        Args:
            t: response time in seconds.

        Returns:
            The time weight in ``[0, 1]``.
        """
        if t <= 0:
            return 1.0
        if t >= self.config.TIME_LIMIT:
            return 0.0
        return 1.0 / (1.0 + (t / self.config.tau_time) ** self.config.p_time)

    def trial_score(self, correct: bool, t: float) -> float:
        """Compute the graded trial score ``s`` (spec: trial score).

        ``s = 0`` if the answer is incorrect or ``t >= TIME_LIMIT``. Otherwise
        ``s = floor + (1 - floor) * w(t)`` where ``floor = slow_correct_credit``.

        Args:
            correct: whether the learner's answer was correct.
            t:       response time in seconds.

        Returns:
            The trial score in ``[0, 1]``.
        """
        if (not correct) or (t >= self.config.TIME_LIMIT):
            return 0.0
        floor = self.config.slow_correct_credit
        return floor + (1.0 - floor) * self.time_weight(t)

    def expected_success(self, b: float) -> float:
        """Predicted success probability ``E`` at the current ``theta`` (spec: ability update).

        ``E = 1 / (1 + exp((b - theta) / tau_diff))`` where
        ``tau_diff = difficulty_scale``.

        Args:
            b: difficulty of the item.

        Returns:
            The logistic expected success in ``(0, 1)``.
        """
        return 1.0 / (1.0 + math.exp((b - self.theta) / self.config.difficulty_scale))

    def update(self, b: float, s: float) -> float:
        """Apply the Elo / 1-PL ability update (spec: ability update).

        ``theta <- theta + K * (s - E)`` with ``E`` evaluated at the
        pre-update ``theta``. Mutates :attr:`theta`.

        Args:
            b: difficulty of the item just answered.
            s: the trial score for that item.

        Returns:
            The new (post-update) ``theta``.
        """
        E = self.expected_success(b)
        self.theta = self.theta + self.config.K * (s - E)
        return self.theta

    @staticmethod
    def cold_start_theta(b_min: float, config: EngineConfig) -> float:
        """Initial ability so the easiest item starts near ``p_start`` (spec: cold start).

        ``theta_init = b_min + tau_diff * ln(p_start / (1 - p_start))``.

        Args:
            b_min:  difficulty of the easiest item in the pool.
            config: engine hyper-parameters.

        Returns:
            The cold-start ability estimate.
        """
        return b_min + config.difficulty_scale * math.log(
            config.p_start / (1.0 - config.p_start)
        )
