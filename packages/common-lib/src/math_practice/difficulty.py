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

_REPDIGITS_2 = frozenset({11, 22, 33, 44, 55, 66, 77, 88, 99})

# Largest ``range_bound`` that uses the coarse two-tier ladder (within-ten vs
# into-the-teens). At or below it every fact is at most "a single digit plus a
# teen", so the five-level structural ladder -- which distinguishes regrouping
# among two-digit operands -- collapses to a sum-based L1/L2 split. Larger ranges
# (the up-to-100 module) keep the full five-level ladder.
_COARSE_LADDER_MAX_RANGE = 20


def _is_repdigit2(n: int) -> bool:
    """Return whether ``n`` is a two-digit repdigit (``11, 22, ..., 99``).

    Args:
        n: the integer to test.

    Returns:
        ``True`` if ``n`` is one of the nine two-digit repdigits.
    """
    return n in _REPDIGITS_2


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


class LeveledDifficultyScorer(DifficultyScorer):
    """Abstract level-and-refinement difficulty scorer (modules design §3).

    Decomposes difficulty into ``b = level + delta`` where ``level`` is a
    structural classifier in ``{1..5}`` (the backbone of the ladder) and
    ``delta`` in ``[0, 1)`` is a within-level magnitude refinement, so ``b``
    lands in ``[level, level + 1)`` for every module.

    ``delta`` is the per-level, per-module min-max normalization of a raw
    hardness key. Because the normalization spans a whole level's members, the
    scorer is **pool-aware**: :meth:`fit` must be called with the module pool
    before :meth:`score` can produce a non-zero ``delta``. This extends the
    lifecycle without changing the :class:`DifficultyScorer` ``score`` contract.

    Subclasses supply the structural classifier (:meth:`classify_level`) and the
    within-level ordering key (:meth:`raw_key`).
    """

    def __init__(self, config: EngineConfig) -> None:
        """Store the config and initialise the (empty) per-level bounds.

        Args:
            config: engine configuration supplying the raw-key weights.
        """
        self._config = config
        self._bounds: dict[int, tuple[float, float]] = {}

    @abc.abstractmethod
    def classify_level(self, exercise: Exercise) -> int:
        """Return the structural level ``1..5`` of ``exercise``.

        Args:
            exercise: the exercise to classify.

        Returns:
            The structural difficulty level.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def raw_key(self, exercise: Exercise) -> float:
        """Return the within-level ordering key of ``exercise``.

        Only the *relative* magnitude matters; the absolute scale is washed out
        by the per-level normalization in :meth:`score`.

        Args:
            exercise: the exercise to rank within its level.

        Returns:
            The raw hardness key.
        """
        raise NotImplementedError

    def level(self, exercise: Exercise) -> int:
        """Return the structural level of ``exercise`` (public lookup).

        A thin alias over :meth:`classify_level` for callers (audit log, UI)
        that want the level without the refinement.

        Args:
            exercise: the exercise to classify.

        Returns:
            The structural difficulty level.
        """
        return self.classify_level(exercise)

    def fit(self, pool: list[Exercise]) -> None:
        """Precompute the per-level ``(min, max)`` of the raw key over ``pool``.

        Groups ``pool`` by :meth:`classify_level` and records each level's raw-key
        range, which :meth:`score` consumes to normalize ``delta``. Must be called
        before scoring; calling it again re-fits from scratch.

        Args:
            pool: the module's full exercise pool to fit against.
        """
        bounds: dict[int, tuple[float, float]] = {}
        for exercise in pool:
            lvl = self.classify_level(exercise)
            key = self.raw_key(exercise)
            lo, hi = bounds.get(lvl, (key, key))
            bounds[lvl] = (min(lo, key), max(hi, key))
        self._bounds = bounds

    def score(self, exercise: Exercise) -> float:
        """Return the difficulty ``b = level + delta`` of ``exercise``.

        ``delta`` is the raw key min-max normalized within the exercise's level.
        When the scorer is unfitted, the level is absent from the fitted bounds,
        or the level's raw keys are all equal (``hi == lo``), ``delta`` is ``0``.
        ``delta`` is clamped to ``[0, 1 - 1e-9]`` so ``b`` stays in
        ``[level, level + 1)``.

        Args:
            exercise: the exercise to score.

        Returns:
            ``float(level) + delta`` in ``[level, level + 1)``.
        """
        lvl = self.classify_level(exercise)
        lo, hi = self._bounds.get(lvl, (0.0, 0.0))
        if hi == lo:
            delta = 0.0
        else:
            delta = (self.raw_key(exercise) - lo) / (hi - lo)
            delta = min(max(delta, 0.0), 1.0 - 1e-9)
        return float(lvl) + delta


class AdditionLevelScorer(LeveledDifficultyScorer):
    """Range-coherent addition ladder with within-level refinement (modules §3.1).

    The depth of the structural ladder tracks the configured ``range_bound``.

    Small-range modules (``range_bound <= _COARSE_LADDER_MAX_RANGE`` -- the
    up-to-10 and up-to-20 modules) use a coarse two-tier split by sum, so every
    in-range fact -- including ``1 + 10`` and ``12 + 8`` -- lands in L1/L2:

        1. sum <= 10  -- within ten      (``3 + 4``)
        2. 11..20     -- into the teens  (``7 + 8``, ``1 + 10``, ``12 + 8``)

    The up-to-100 module (and any out-of-range fact, e.g. the standalone sanity
    facts scored under a default range) uses the five-level structural ladder
    (first matching rule wins):

        1. both single-digit, sum <= 10            (``3 + 4``)
        2. both single-digit crossing ten, or both nonzero multiples of ten
           (``7 + 8``, ``40 + 30``)
        3. both two-digit repdigits                (``44 + 33``)
        4. two-digit-ish, no regrouping            (``24 + 13``)
        5. two-digit-ish, with regrouping          (``58 + 25``)

    The within-level key reuses today's addition formula
    ``w_mag*max(a, b) + w_order*1[a<b] - w_double*1[a==b]``.
    """

    def classify_level(self, exercise: Exercise) -> int:
        """Return the addition structural level (range-coherent; modules §3.1).

        Args:
            exercise: the addition exercise to classify.

        Returns:
            For an in-range fact of a small-range module
            (``range_bound <= _COARSE_LADDER_MAX_RANGE``), the coarse two-tier
            level (``1`` for sum ``<= 10``, ``2`` for ``11..20``). Otherwise the
            first matching five-level rule: single-digit easy/crossing, round
            tens, repdigits, then regroup vs no-regroup for the remainder.
        """
        a, b = exercise.a, exercise.b
        # Coarse two-tier ladder for the up-to-10 / up-to-20 modules. Gated to
        # in-range facts so the five-level ladder still classifies larger facts
        # (the up-to-100 pool, and the standalone sanity facts a default-range
        # config scores absolutely).
        if (
            self._config.range_bound <= _COARSE_LADDER_MAX_RANGE
            and a + b <= self._config.range_bound
        ):
            return 1 if a + b <= 10 else 2
        if a < 10 and b < 10:
            return 1 if a + b <= 10 else 2
        if a % 10 == 0 and b % 10 == 0:
            return 2
        if _is_repdigit2(a) and _is_repdigit2(b):
            return 3
        return 5 if (a % 10 + b % 10) >= 10 else 4

    def raw_key(self, exercise: Exercise) -> float:
        """Return the within-level addition ordering key.

        Args:
            exercise: the addition exercise to rank.

        Returns:
            ``w_mag*max(a, b) + w_order*1[a<b] - w_double*1[a==b]``.
        """
        cfg = self._config
        a, b = exercise.a, exercise.b
        key = cfg.w_mag * max(a, b)
        if a < b:
            key += cfg.w_order
        if a == b:
            key -= cfg.w_double
        return key


class SubtractionLevelScorer(LeveledDifficultyScorer):
    """Range-coherent subtraction ladder with within-level refinement (modules §3.2).

    Minuend ``a`` and subtrahend ``b`` satisfy ``a >= b >= 1`` (guaranteed by the
    pool). The depth of the structural ladder tracks the configured ``range_bound``.

    Small-range modules (``range_bound <= _COARSE_LADDER_MAX_RANGE`` -- the
    up-to-10 and up-to-20 modules) use a coarse two-tier split by minuend, so
    every in-range fact -- including ``11 - 1`` and ``15 - 7`` -- lands in L1/L2:

        1. minuend <= 10  -- within ten      (``9 - 4``)
        2. minuend 11..20 -- into the teens  (``15 - 7``, ``11 - 1``)

    The up-to-100 module (and any out-of-range fact, e.g. the standalone sanity
    facts scored under a default range) uses the five-level structural ladder
    (first matching rule wins):

        1. minuend <= 10 (within ten)                  (``9 - 4``)
        2. round tens, or teen borrow with single-digit subtrahend
           (``70 - 30``, ``15 - 7``)
        3. both two-digit repdigits                    (``66 - 33``)
        4. two-digit-ish, no borrow                    (``47 - 23``)
        5. two-digit-ish, with borrow                  (``52 - 27``)

    The within-level key ``w_mag*a + w_sub*b`` is minuend-dominant: a larger
    subtrahend makes the same minuend harder.
    """

    def classify_level(self, exercise: Exercise) -> int:
        """Return the subtraction structural level (range-coherent; modules §3.2).

        Args:
            exercise: the subtraction exercise to classify.

        Returns:
            For an in-range fact of a small-range module
            (``range_bound <= _COARSE_LADDER_MAX_RANGE``), the coarse two-tier
            level (``1`` for minuend ``<= 10``, ``2`` for ``11..20``). Otherwise
            the first matching five-level rule: within-ten, round-tens/teen-borrow,
            repdigits, then borrow vs no-borrow for the remainder.
        """
        a, b = exercise.a, exercise.b
        # Coarse two-tier ladder for the up-to-10 / up-to-20 modules; see
        # AdditionLevelScorer.classify_level for the in-range gate rationale.
        if (
            self._config.range_bound <= _COARSE_LADDER_MAX_RANGE
            and a <= self._config.range_bound
        ):
            return 1 if a <= 10 else 2
        if a <= 10:
            return 1
        if a % 10 == 0 and b % 10 == 0:
            return 2
        if 11 <= a <= 19 and b < 10 and (a % 10) < b:
            return 2
        if _is_repdigit2(a) and _is_repdigit2(b):
            return 3
        return 5 if (a % 10) < (b % 10) else 4

    def raw_key(self, exercise: Exercise) -> float:
        """Return the within-level subtraction ordering key.

        Args:
            exercise: the subtraction exercise to rank.

        Returns:
            ``w_mag*a + w_sub*b`` (minuend-dominant; larger subtrahend harder).
        """
        cfg = self._config
        return cfg.w_mag * exercise.a + cfg.w_sub * exercise.b


def default_scorer_for(
    config: EngineConfig, pool: list[Exercise] | None = None
) -> DifficultyScorer:
    """Build the leveled scorer for ``config.op``, optionally fitting it.

    Dispatches on the operator to the matching :class:`LeveledDifficultyScorer`
    subclass. When ``pool`` is supplied the scorer is fitted to it (so ``delta``
    is live) before being returned; otherwise an unfitted scorer is returned and
    must be :meth:`~LeveledDifficultyScorer.fit`-ted before it produces a
    non-zero ``delta``.

    Args:
        config: engine configuration; ``config.op`` selects the scorer.
        pool: optional exercise pool to fit the scorer against.

    Returns:
        A leveled scorer matching ``config.op``.

    Raises:
        ValueError: if ``config.op`` is neither ``"+"`` nor ``"-"``.
    """
    if config.op == "+":
        scorer: LeveledDifficultyScorer = AdditionLevelScorer(config)
    elif config.op == "-":
        scorer = SubtractionLevelScorer(config)
    else:
        raise ValueError(f"unknown op: {config.op!r}")
    if pool is not None:
        scorer.fit(pool)
    return scorer
