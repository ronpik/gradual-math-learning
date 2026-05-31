"""Pytest-free round-trip test for the snapshot/restore seam (spec v1, state).

Runnable directly:

    cd /Users/ronp/workspace/math-learn && \
        uv run --package math-practice python packages/common-lib/tests/test_state.py

Proves, with plain asserts, that:

  * snapshot() captures theta, a *copy* of config, every exercise's mastery
    state, and last_shown as (a, b);
  * from_state() rebuilds a behaviourally identical engine (same theta, mastery,
    last_shown, curriculum size);
  * the rebuilt engine continues consistently: next_exercise excludes the
    restored last_shown, and submit updates the restored theta/mastery exactly
    like the original would have.
"""

from __future__ import annotations

import math
import random

from math_practice import (
    EngineConfig,
    EngineState,
    Exercise,
    ExerciseMastery,
    PracticeEngine,
)


def _mastery_map(engine: PracticeEngine) -> dict[tuple[int, int], tuple[int, int, bool]]:
    """Return a comparable {(a, b): (streak, faults, mastered)} view of mastery."""
    out: dict[tuple[int, int], tuple[int, int, bool]] = {}
    for ex, st in engine._mastery.items():  # noqa: SLF001 - test introspection
        out[(ex.a, ex.b)] = (st.streak, st.faults, st.mastered)
    return out


def run_session(engine: PracticeEngine, trials: int, rng: random.Random) -> None:
    """Drive ``trials`` semi-random trials so mastery/theta diverge from defaults."""
    for _ in range(trials):
        ex = engine.next_exercise()
        # Mostly fast-correct (builds streaks/mastery + raises theta), with the
        # occasional slow/incorrect answer to populate faults too.
        roll = rng.random()
        if roll < 0.75:
            engine.submit(ex, correct=True, response_time=rng.uniform(0.5, 3.0))
        elif roll < 0.90:
            engine.submit(ex, correct=True, response_time=rng.uniform(11.0, 20.0))
        else:
            engine.submit(ex, correct=False, response_time=rng.uniform(1.0, 5.0))


def check_round_trip() -> None:
    """Snapshot engine A after ~30 trials, rebuild B, assert full equality."""
    rng_a = random.Random(2026)
    engine_a = PracticeEngine(rng=rng_a)
    run_session(engine_a, trials=30, rng=rng_a)

    snap = engine_a.snapshot()

    # --- snapshot shape / value checks --------------------------------------
    assert isinstance(snap, EngineState)
    assert isinstance(snap.config, EngineConfig)
    assert snap.config == engine_a.config, "config copy must equal the original"
    assert snap.config is not engine_a.config, "snapshot must hold a COPY of config"
    assert math.isclose(snap.theta, engine_a.theta)

    assert all(isinstance(m, ExerciseMastery) for m in snap.mastery)
    assert len(snap.mastery) == engine_a.total(), "mastery must cover full curriculum"

    # last_shown is the (a, b) of the most recently drawn exercise.
    assert snap.last_shown == (
        engine_a._last_shown.a,  # noqa: SLF001 - test introspection
        engine_a._last_shown.b,  # noqa: SLF001
    )
    print(
        f"[ok] snapshot: theta={snap.theta:.4f}, "
        f"mastery_items={len(snap.mastery)}, last_shown={snap.last_shown}"
    )

    # --- rebuild engine B ----------------------------------------------------
    engine_b = PracticeEngine.from_state(snap, rng=random.Random(99))

    assert math.isclose(engine_b.theta, engine_a.theta), "theta must match after restore"
    assert engine_b.total() == engine_a.total()
    assert engine_b.mastered_count() == engine_a.mastered_count()
    assert _mastery_map(engine_b) == _mastery_map(engine_a), "mastery must match exactly"
    assert (
        engine_b._last_shown == engine_a._last_shown  # noqa: SLF001
    ), "last_shown must match after restore"
    print(
        f"[ok] restored engine B: theta={engine_b.theta:.4f}, "
        f"mastered={engine_b.mastered_count()}/{engine_b.total()}, "
        f"last_shown={engine_b._last_shown}"  # noqa: SLF001
    )

    # --- B excludes last_shown on its very next draw ------------------------
    excluded = engine_b._last_shown  # noqa: SLF001
    for _ in range(50):
        drawn = engine_b.next_exercise()
        assert drawn != excluded, "first draw after restore must exclude last_shown"
        # restore last_shown so we keep testing the exclusion of the SAME item
        engine_b._last_shown = excluded  # noqa: SLF001
    print(f"[ok] engine B excludes restored last_shown {excluded} on next draw")

    # --- B continues consistently: submit updates restored theta/mastery ----
    engine_b._last_shown = None  # noqa: SLF001 - draw fresh, no exclusion
    target = Exercise(a=2, b=3)
    before = engine_b._mastery.state(target)  # noqa: SLF001
    before_snapshot = (before.streak, before.faults, before.mastered)
    theta_before = engine_b.theta

    result = engine_b.submit(target, correct=True, response_time=1.0)

    assert math.isclose(result.theta_before, theta_before)
    assert math.isclose(engine_b.theta, result.theta_after)
    assert result.theta_after != theta_before, "fast-correct submit must move theta"
    after = engine_b._mastery.state(target)  # noqa: SLF001
    assert (after.streak, after.faults, after.mastered) != before_snapshot or (
        before_snapshot[2] is True
    ), "submit must advance restored mastery (unless already mastered)"
    print(
        f"[ok] engine B continues: theta {theta_before:.4f} -> {engine_b.theta:.4f}, "
        f"mastery(2+3) {before_snapshot} -> "
        f"{(after.streak, after.faults, after.mastered)}"
    )

    # --- snapshot independence: mutating A must not change the snapshot -----
    pre_theta = snap.theta
    run_session(engine_a, trials=5, rng=rng_a)
    assert math.isclose(snap.theta, pre_theta), "snapshot must be decoupled from A"
    print("[ok] snapshot is decoupled from later mutations of engine A")


def check_empty_last_shown() -> None:
    """A brand-new engine snapshots last_shown=None and round-trips cleanly."""
    engine = PracticeEngine(rng=random.Random(1))
    snap = engine.snapshot()
    assert snap.last_shown is None, "fresh engine has no last_shown"
    rebuilt = PracticeEngine.from_state(snap, rng=random.Random(1))
    assert rebuilt._last_shown is None  # noqa: SLF001
    assert math.isclose(rebuilt.theta, engine.theta)
    # next_exercise works with no exclusion.
    ex = rebuilt.next_exercise()
    assert isinstance(ex, Exercise)
    print("[ok] fresh-engine snapshot/restore (last_shown=None) works")


def main() -> None:
    check_round_trip()
    check_empty_last_shown()
    print("\nALL STATE CHECKS PASSED")


if __name__ == "__main__":
    main()
