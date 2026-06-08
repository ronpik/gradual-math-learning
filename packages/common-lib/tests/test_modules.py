"""Pytest-free checks for the six problem modules (modules design §2).

Runnable directly:

    cd /Users/ronp/workspace/math-learn && \
        uv run --package math-practice python \
        packages/common-lib/tests/test_modules.py

For every module in :data:`MODULES`, verifies with plain asserts that:

  * the pool is non-empty and well-formed -- subtraction pools satisfy
    ``a >= b >= 1`` and ``a <= range_bound``; addition pools satisfy
    ``a + b <= range_bound`` (with both operands >= 1);
  * a :class:`PracticeEngine` built from the module's config can draw an
    exercise, grade a fast-correct answer, and snapshot/restore so that theta,
    mastery, and last_shown round-trip and the restored engine draws
    deterministically under a seeded rng;
  * ``level_progress()`` reports exactly the module's applicable levels.
"""

from __future__ import annotations

import math
import random

from math_practice import MODULES, Exercise, PracticeEngine


def _expected_answer(ex: Exercise) -> int:
    """Return the correct answer for ``ex`` given its operator."""
    return ex.a + ex.b if ex.op == "+" else ex.a - ex.b


def _mastery_map(engine: PracticeEngine) -> dict[tuple[int, int], tuple[int, int, bool]]:
    """Return a comparable {(a, b): (streak, faults, mastered)} view of mastery."""
    out: dict[tuple[int, int], tuple[int, int, bool]] = {}
    for ex, st in engine._mastery.items():  # noqa: SLF001 - test introspection
        out[(ex.a, ex.b)] = (st.streak, st.faults, st.mastered)
    return out


def check_pool_wellformed() -> None:
    """Every module pool is non-empty and within its operation's range bound."""
    for module_id, spec in MODULES.items():
        pool = spec.build_pool()
        assert pool, f"{module_id}: pool is empty"
        assert spec.op in ("+", "-"), f"{module_id}: unexpected op {spec.op!r}"
        for ex in pool:
            assert ex.op == spec.op, f"{module_id}: {ex} has wrong op"
            assert ex.a >= 1 and ex.b >= 1, f"{module_id}: {ex} has operand < 1"
            if spec.op == "-":
                # Minuend-bounded; no negative results.
                assert ex.a >= ex.b, f"{module_id}: {ex} has a < b"
                assert ex.a <= spec.range_bound, (
                    f"{module_id}: minuend {ex.a} > range_bound {spec.range_bound}"
                )
            else:
                # Sum-bounded.
                assert ex.a + ex.b <= spec.range_bound, (
                    f"{module_id}: sum {ex.a}+{ex.b} > range_bound {spec.range_bound}"
                )
        print(f"[ok] {module_id}: pool well-formed ({len(pool)} items)")


def check_engine_round_trip() -> None:
    """Each module engine draws, grades, and round-trips through a snapshot."""
    for module_id, spec in MODULES.items():
        config = spec.build_config()

        engine = PracticeEngine(config=config, rng=random.Random(7))
        ex = engine.next_exercise()
        assert ex.op == spec.op, f"{module_id}: drawn {ex} has wrong op"

        # Submit a correct, fast answer (well under any mastery_time_limit).
        result = engine.submit(ex, correct=True, response_time=1.0)
        assert result.correct is True
        assert result.exercise == ex
        # The drawn exercise carries a structural level (1..5 for a leveled
        # scorer); whether it stays within the module's *declared* applicable
        # levels is asserted exhaustively in check_level_progress.
        assert result.level >= 1, f"{module_id}: drawn level {result.level} < 1"
        # A fast-correct answer scores high and moves theta.
        assert result.s > 0.9, f"{module_id}: fast-correct score {result.s} too low"
        assert math.isclose(engine.theta, result.theta_after)

        # Snapshot -> restore under a *different* seed; behaviour must match.
        snap = engine.snapshot()
        assert snap.config.op == spec.op
        assert snap.config.range_bound == spec.range_bound

        restored = PracticeEngine.from_state(snap, rng=random.Random(123))
        assert math.isclose(restored.theta, engine.theta), (
            f"{module_id}: theta did not round-trip"
        )
        assert restored.total() == engine.total()
        assert restored.mastered_count() == engine.mastered_count()
        assert _mastery_map(restored) == _mastery_map(engine), (
            f"{module_id}: mastery did not round-trip"
        )
        assert (
            restored._last_shown == engine._last_shown  # noqa: SLF001
        ), f"{module_id}: last_shown did not round-trip"
        # The restored engine excludes last_shown on its next draw.
        nxt = restored.next_exercise()
        assert nxt != engine._last_shown, (  # noqa: SLF001
            f"{module_id}: restored draw failed to exclude last_shown"
        )

        # Determinism: two restores under the SAME seed draw identically.
        twin_a = PracticeEngine.from_state(snap, rng=random.Random(2024))
        twin_b = PracticeEngine.from_state(snap, rng=random.Random(2024))
        draws_a = [twin_a.next_exercise() for _ in range(20)]
        draws_b = [twin_b.next_exercise() for _ in range(20)]
        assert draws_a == draws_b, (
            f"{module_id}: restored engine not deterministic under a seeded rng"
        )
        # The grade is op-correct for the restored draws too.
        for drawn in draws_a:
            assert _expected_answer(drawn) == (
                drawn.a + drawn.b if drawn.op == "+" else drawn.a - drawn.b
            )

        print(f"[ok] {module_id}: engine draw/grade/snapshot round-trip + determinism")


def check_level_progress() -> None:
    """``level_progress`` reports exactly each module's applicable levels.

    Aggregates the per-module check so a single failure names every offending
    module rather than short-circuiting on the first one.
    """
    mismatches: list[str] = []
    for module_id, spec in MODULES.items():
        engine = PracticeEngine(config=spec.build_config(), rng=random.Random(1))
        progress = engine.level_progress()

        reported = tuple(sorted(progress.keys()))
        expected = tuple(sorted(spec.applicable_levels))

        # Each bucket is (mastered, total) with total > 0 and mastered <= total;
        # a fresh engine has mastered 0 everywhere. These structural invariants
        # hold regardless of the applicable-levels question.
        for level, (mastered, total) in progress.items():
            assert total > 0, f"{module_id}: level {level} has empty bucket"
            assert 0 <= mastered <= total
            assert mastered == 0, f"{module_id}: fresh engine should master nothing"

        if reported != expected:
            mismatches.append(
                f"{module_id}: level_progress levels {reported} != "
                f"applicable_levels {expected}"
            )
        else:
            print(f"[ok] {module_id}: level_progress levels = {reported}")

    assert not mismatches, "level_progress() returned non-applicable levels:\n  " + (
        "\n  ".join(mismatches)
    )


def main() -> None:
    check_pool_wellformed()
    check_engine_round_trip()
    check_level_progress()
    print("\nALL MODULE CHECKS PASSED")


if __name__ == "__main__":
    main()
