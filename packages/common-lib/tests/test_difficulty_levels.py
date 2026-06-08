"""Pytest-free checks for the leveled difficulty ladders (modules design §3).

Runnable directly:

    cd /Users/ronp/workspace/math-learn && \
        uv run --package math-practice python \
        packages/common-lib/tests/test_difficulty_levels.py

Verifies, with plain asserts, for BOTH :class:`AdditionLevelScorer` and
:class:`SubtractionLevelScorer`:

  * ``classify_level`` assigns the shared sanity facts to the documented level
    (3+4->1, 7+8->2, 40+30->2, 44+33->3, 24+13->4, 58+25->5; 9-4->1, 70-30->2,
    15-7->2, 66-33->3, 47-23->4, 52-27->5);
  * after ``fit`` on a module's pool every ``score`` (``b = level + delta``)
    lands in ``[level, level + 1)``;
  * within a level a larger-raw-key item scores ``b`` no smaller than a
    smaller-raw-key one (the within-level ordering is monotone).
"""

from __future__ import annotations

from math_practice import (
    AdditionLevelScorer,
    EngineConfig,
    Exercise,
    SubtractionLevelScorer,
    get_module,
)

# Shared sanity facts (modules design §3.1 / §3.2). Keyed by (a, b) -> level.
_ADD_FACTS: dict[tuple[int, int], int] = {
    (3, 4): 1,
    (7, 8): 2,
    (40, 30): 2,
    (44, 33): 3,
    (24, 13): 4,
    (58, 25): 5,
}
_SUB_FACTS: dict[tuple[int, int], int] = {
    (9, 4): 1,
    (70, 30): 2,
    (15, 7): 2,
    (66, 33): 3,
    (47, 23): 4,
    (52, 27): 5,
}


def check_classify_addition() -> None:
    """``AdditionLevelScorer.classify_level`` matches the addition sanity facts."""
    scorer = AdditionLevelScorer(EngineConfig(op="+"))
    for (a, b), want in _ADD_FACTS.items():
        got = scorer.classify_level(Exercise(a=a, b=b, op="+"))
        assert got == want, f"classify {a}+{b}={got}, expected {want}"
    print(f"[ok] addition classify_level matches {len(_ADD_FACTS)} sanity facts")


def check_classify_subtraction() -> None:
    """``SubtractionLevelScorer.classify_level`` matches the subtraction facts."""
    scorer = SubtractionLevelScorer(EngineConfig(op="-"))
    for (a, b), want in _SUB_FACTS.items():
        got = scorer.classify_level(Exercise(a=a, b=b, op="-"))
        assert got == want, f"classify {a}-{b}={got}, expected {want}"
    print(f"[ok] subtraction classify_level matches {len(_SUB_FACTS)} sanity facts")


def _check_score_bounds_and_monotone(
    scorer: AdditionLevelScorer | SubtractionLevelScorer,
    pool: list[Exercise],
    label: str,
) -> None:
    """Assert b in [level, level+1) and within-level raw-key monotonicity.

    After the scorer is fitted to ``pool``, every exercise's ``score`` must land
    in its level's unit band, and within a level an item with a larger raw key
    must score ``b`` no smaller than one with a smaller raw key.

    Args:
        scorer: the fitted leveled scorer under test.
        pool:   the module pool the scorer was fitted to.
        label:  human-readable tag for assertion messages.
    """
    # b lands in [level, level + 1) for every exercise.
    for ex in pool:
        lvl = scorer.classify_level(ex)
        b = scorer.score(ex)
        assert float(lvl) <= b < float(lvl) + 1.0, (
            f"{label}: b({ex})={b} outside [{lvl}, {lvl + 1}) for level {lvl}"
        )

    # Within each level, larger raw key -> b not smaller (delta is a monotone
    # min-max normalization of the raw key, so b mirrors the raw ordering).
    by_level: dict[int, list[Exercise]] = {}
    for ex in pool:
        by_level.setdefault(scorer.classify_level(ex), []).append(ex)

    levels_checked = 0
    for lvl, items in by_level.items():
        ordered = sorted(items, key=scorer.raw_key)
        if len(ordered) < 2:
            continue
        levels_checked += 1
        lo_ex, hi_ex = ordered[0], ordered[-1]
        assert scorer.raw_key(hi_ex) >= scorer.raw_key(lo_ex)
        # The smallest-raw-key item is the lowest b in its level, the largest the
        # highest -- and any adjacent pair respects the ordering.
        for prev, nxt in zip(ordered, ordered[1:]):
            if scorer.raw_key(nxt) > scorer.raw_key(prev):
                assert scorer.score(nxt) >= scorer.score(prev), (
                    f"{label} L{lvl}: b not monotone for {prev} -> {nxt}"
                )
        # The level-min item sits at b == level (delta == 0).
        assert scorer.score(lo_ex) == float(lvl), (
            f"{label} L{lvl}: min-key item {lo_ex} should have delta 0"
        )
    print(
        f"[ok] {label}: b in [level, level+1) for {len(pool)} items; "
        f"within-level monotone over {levels_checked} multi-item level(s)"
    )


def check_addition_fit_bounds() -> None:
    """Fit the addition scorer on add_100 and assert bounds + monotonicity."""
    spec = get_module("add_100")
    pool = spec.build_pool()
    scorer = AdditionLevelScorer(spec.build_config())
    scorer.fit(pool)
    _check_score_bounds_and_monotone(scorer, pool, "add_100")


def check_subtraction_fit_bounds() -> None:
    """Fit the subtraction scorer on sub_100 and assert bounds + monotonicity."""
    spec = get_module("sub_100")
    pool = spec.build_pool()
    scorer = SubtractionLevelScorer(spec.build_config())
    scorer.fit(pool)
    _check_score_bounds_and_monotone(scorer, pool, "sub_100")


def main() -> None:
    check_classify_addition()
    check_classify_subtraction()
    check_addition_fit_bounds()
    check_subtraction_fit_bounds()
    print("\nALL DIFFICULTY-LEVEL CHECKS PASSED")


if __name__ == "__main__":
    main()
