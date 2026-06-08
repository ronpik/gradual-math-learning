"""Problem-module catalog (modules design §2).

A **module** is one operation paired with one range -- e.g. addition with sums
up to 20, or subtraction with minuends up to 100. Each is a :class:`ModuleSpec`
that ties together the four things a module needs: the :class:`EngineConfig`
(with per-module time knobs), the deterministic exercise pool, and the fitted
:class:`~math_practice.difficulty.DifficultyScorer` for its operation.

:data:`MODULES` is the canonical registry of the six modules; :func:`get_module`
resolves a module id to its spec. The engine stays module-agnostic -- callers
resolve an id to a config + scorer here, then hand the config to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import EngineConfig
from .difficulty import DifficultyScorer, default_scorer_for
from .models import Exercise, build_curriculum

_CURRICULUM_CACHE: dict[tuple[str, int], list[Exercise]] = {}
_LEVEL_POOL_CACHE: dict[tuple[str, int, tuple[int, ...]], list[Exercise]] = {}


def curriculum_for(
    op: str,
    range_bound: int,
    applicable_levels: tuple[int, ...] | None = None,
) -> list[Exercise]:
    """Return the memoized curriculum for ``(op, range_bound)``.

    Caches :func:`~math_practice.models.build_curriculum` results in a
    process-level dict keyed by ``(op, range_bound)`` so each module's pool
    (up to ~10k items for the up-to-100 modules) is built once, not per call.

    When ``applicable_levels`` is given the cached pool is further restricted to
    the items whose structural level (via the leveled scorer for ``op``) falls in
    that set -- a module only contains the subset its range permits (modules
    design §2) -- and that filtered list is memoized separately. ``None`` returns
    the full pool unchanged.

    The returned list is the shared cached instance: **callers must not mutate
    it** (the softmax selection and the per-level fit both read it whole).

    Args:
        op: binary operator symbol; ``"+"`` or ``"-"``.
        range_bound: inclusive curriculum bound -- the sum bound for addition
            or the minuend bound for subtraction.
        applicable_levels: optional subset of structural levels ``1..5`` to keep;
            ``None`` keeps every item.

    Returns:
        The cached curriculum as a list of :class:`Exercise` objects.
    """
    key = (op, range_bound)
    pool = _CURRICULUM_CACHE.get(key)
    if pool is None:
        pool = build_curriculum(range_bound, op=op)
        _CURRICULUM_CACHE[key] = pool
    if applicable_levels is None:
        return pool

    levels = tuple(sorted(applicable_levels))
    filtered_key = (op, range_bound, levels)
    filtered = _LEVEL_POOL_CACHE.get(filtered_key)
    if filtered is None:
        allowed = frozenset(levels)
        # An unfitted leveled scorer classifies on structure alone; delta (which
        # needs a fit) is irrelevant to level membership. The classifier must see
        # this module's ``range_bound`` -- the leveled ladders are range-coherent
        # (small ranges use a coarse two-tier split), so a default-range scorer
        # would misclassify the up-to-20 facts and wrongly drop them.
        classifier = default_scorer_for(EngineConfig(op=op, range_bound=range_bound))
        level = getattr(classifier, "level", None)
        filtered = (
            [ex for ex in pool if level(ex) in allowed]
            if callable(level)
            else list(pool)
        )
        _LEVEL_POOL_CACHE[filtered_key] = filtered
    return filtered


@dataclass(frozen=True)
class ModuleSpec:
    """A single problem module: operation x range x scorer x config (§2).

    Frozen pedagogical data describing one practice module. It builds the three
    engine inputs on demand -- a merged :class:`EngineConfig`, the exercise pool,
    and a fitted scorer -- while the engine itself only ever consumes the config.

    Attributes:
        id:                 stable module id (``"add_10"`` ... ``"sub_100"``).
        op:                 binary operator symbol; ``"+"`` or ``"-"``.
        range_bound:        curriculum bound -- the sum bound for addition
                            (``a + b <= range_bound``) or the minuend bound for
                            subtraction (``a <= range_bound``).
        label:              human-readable display name for the module.
        applicable_levels:  the subset of structural levels ``1..5`` this
                            module's range permits.
        config_overrides:   per-module knob overrides merged onto the
                            :class:`EngineConfig` defaults (time knobs scale with
                            difficulty); empty for the up-to-10 modules.
    """

    id: str
    op: str
    range_bound: int
    label: str
    applicable_levels: tuple[int, ...]
    config_overrides: dict = field(default_factory=dict)

    def build_config(self) -> EngineConfig:
        """Return the module's :class:`EngineConfig` with overrides applied.

        Pins ``op`` and ``range_bound`` to this module and sets ``MAX_SUM`` to
        ``range_bound`` for addition (so the sum bound and back-compat alias
        agree) or to the default for subtraction (where ``range_bound`` bounds
        the minuend, not a sum), carries the module's ``applicable_levels`` so the
        engine restricts the pool to the levels its range permits, then layers the
        per-module ``config_overrides``.

        Returns:
            The merged :class:`EngineConfig` for this module.
        """
        max_sum = self.range_bound if self.op == "+" else EngineConfig().MAX_SUM
        return EngineConfig(
            op=self.op,
            range_bound=self.range_bound,
            MAX_SUM=max_sum,
            applicable_levels=self.applicable_levels,
            **self.config_overrides,
        )

    def build_pool(self) -> list[Exercise]:
        """Return the module's exercise pool (memoized).

        Delegates to :func:`curriculum_for` with the module's
        ``applicable_levels``, so the pool is restricted to the structural levels
        its range permits and repeated calls share one cached list. **Callers must
        not mutate the result.**

        Returns:
            The module's curriculum as a list of :class:`Exercise` objects.
        """
        return curriculum_for(
            self.op, self.range_bound, self.applicable_levels
        )

    def build_scorer(self, config: EngineConfig) -> DifficultyScorer:
        """Return the module's difficulty scorer, fitted to its pool.

        Dispatches on ``config.op`` via
        :func:`~math_practice.difficulty.default_scorer_for` and fits the leveled
        scorer to this module's pool so ``delta`` is live.

        Args:
            config: engine configuration; ``config.op`` selects the scorer.

        Returns:
            The fitted :class:`~math_practice.difficulty.DifficultyScorer` for
            this module.
        """
        return default_scorer_for(config, self.build_pool())


MODULES: dict[str, ModuleSpec] = {
    "add_10": ModuleSpec(
        id="add_10",
        op="+",
        range_bound=10,
        label="Addition up to 10",
        applicable_levels=(1,),
    ),
    "add_20": ModuleSpec(
        id="add_20",
        op="+",
        range_bound=20,
        label="Addition up to 20",
        applicable_levels=(1, 2),
        config_overrides={
            "mastery_time_limit": 15.0,
            "tau_time": 16.0,
            "TIME_LIMIT": 120.0,
        },
    ),
    "add_100": ModuleSpec(
        id="add_100",
        op="+",
        range_bound=100,
        label="Addition up to 100",
        applicable_levels=(1, 2, 3, 4, 5),
        config_overrides={
            "mastery_time_limit": 28.0,
            "tau_time": 22.0,
            "TIME_LIMIT": 180.0,
        },
    ),
    "sub_10": ModuleSpec(
        id="sub_10",
        op="-",
        range_bound=10,
        label="Subtraction up to 10",
        applicable_levels=(1,),
    ),
    "sub_20": ModuleSpec(
        id="sub_20",
        op="-",
        range_bound=20,
        label="Subtraction up to 20",
        applicable_levels=(1, 2),
        config_overrides={
            "mastery_time_limit": 15.0,
            "tau_time": 16.0,
            "TIME_LIMIT": 120.0,
        },
    ),
    "sub_100": ModuleSpec(
        id="sub_100",
        op="-",
        range_bound=100,
        label="Subtraction up to 100",
        applicable_levels=(1, 2, 3, 4, 5),
        config_overrides={
            "mastery_time_limit": 28.0,
            "tau_time": 22.0,
            "TIME_LIMIT": 180.0,
        },
    ),
}


def get_module(module_id: str) -> ModuleSpec:
    """Resolve a module id to its :class:`ModuleSpec`.

    Args:
        module_id: the id to look up (``"add_10"`` ... ``"sub_100"``).

    Returns:
        The registered :class:`ModuleSpec`.

    Raises:
        ValueError: if ``module_id`` is not a registered module.
    """
    try:
        return MODULES[module_id]
    except KeyError:
        raise ValueError(f"unknown module id: {module_id!r}") from None
