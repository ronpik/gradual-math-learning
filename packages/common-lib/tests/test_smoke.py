"""Pytest-free smoke test for the adaptive-practice engine (spec v1).

Runnable directly:

    cd /Users/ronp/workspace/math-learn && \
        uv run --package math-practice python packages/common-lib/tests/test_smoke.py

Verifies, with plain asserts:

  * curriculum size for MAX_SUM=10,
  * the difficulty sample-table values,
  * the cold-start theta is ~4.6,
  * a ~200-trial simulated session runs and theta rises under fast-correct
    answers.
"""

from __future__ import annotations

import math
import random

from math_practice import (
    AbilityTracker,
    AdditionFixedDifficultyScorer,
    EngineConfig,
    Exercise,
    PracticeEngine,
    build_curriculum,
)


def check_curriculum_size() -> None:
    """MAX_SUM=10 -> ordered pairs a,b>=1, a+b<=10 -> 45 exercises."""
    curriculum = build_curriculum(10)
    # For a=1..9, b runs 1..(10-a): sum_{a=1}^{9}(10-a)=9+8+...+1=45 ordered pairs.
    assert len(curriculum) == 45, f"expected 45 exercises, got {len(curriculum)}"
    for ex in curriculum:
        assert ex.a >= 1 and ex.b >= 1 and ex.a + ex.b <= 10
    print(f"[ok] curriculum size = {len(curriculum)}")


def check_difficulty_table() -> None:
    """Sample difficulty table from the spec / scorer docstring."""
    scorer = AdditionFixedDifficultyScorer(EngineConfig())
    expected = {
        (1, 1): 0.25,
        (2, 1): 2.00,
        (1, 2): 2.50,
        (5, 5): 4.25,
        (7, 2): 7.00,
        (2, 7): 7.50,
    }
    for (a, b), want in expected.items():
        got = scorer.score(Exercise(a, b))
        assert math.isclose(got, want), f"b({a}+{b})={got}, expected {want}"
    print("[ok] difficulty sample table matches:", expected)


def check_cold_start() -> None:
    """Cold-start theta over the curriculum should be ~4.6."""
    cfg = EngineConfig()
    scorer = AdditionFixedDifficultyScorer(cfg)
    curriculum = build_curriculum(cfg.MAX_SUM)
    b_min = min(scorer.score(ex) for ex in curriculum)
    theta = AbilityTracker.cold_start_theta(b_min, cfg)
    # b_min = 0.25 (for 1+1); 0.25 + 2.0*ln(0.9/0.1) = 0.25 + 2.0*2.1972 = 4.644.
    assert 4.5 <= theta <= 4.8, f"cold-start theta {theta} not ~4.6"
    print(f"[ok] cold-start theta = {theta:.4f} (~4.6), b_min={b_min}")


def check_session_theta_rises() -> None:
    """A ~200-trial fast-correct session should leave theta above cold start."""
    engine = PracticeEngine(rng=random.Random(42))
    start_theta = engine.theta

    thetas = [start_theta]
    for _ in range(200):
        ex = engine.next_exercise()
        # Fast and correct: 1.0s response -> high score, theta should climb.
        result = engine.submit(ex, correct=True, response_time=1.0)
        thetas.append(result.theta_after)
        # Engine theta stays in sync with the reported result.
        assert math.isclose(engine.theta, result.theta_after)
        # E captured before update is a valid probability.
        assert 0.0 < result.E < 1.0
        # Fast-correct score is high (near 1, well above mastery threshold).
        assert result.s > 0.9

    end_theta = engine.theta
    assert end_theta > start_theta, (
        f"theta did not rise: start={start_theta:.3f} end={end_theta:.3f}"
    )
    print(
        f"[ok] 200-trial fast-correct session: theta {start_theta:.3f} -> "
        f"{end_theta:.3f} (rose by {end_theta - start_theta:.3f})"
    )
    print(
        f"[ok] mastered {engine.mastered_count()}/{engine.total()} exercises; "
        f"all_mastered={engine.all_mastered()}"
    )


def main() -> None:
    check_curriculum_size()
    check_difficulty_table()
    check_cold_start()
    check_session_theta_rises()
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
