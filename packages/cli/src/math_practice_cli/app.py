"""Terminal practice app for the adaptive math engine (CLI front-end).

This module is the console entry point registered as ``math-practice``. It
drives one learner's session against
:class:`math_practice.PracticeEngine`:

* an **interactive** mode that prompts a child for answers, times the
  response with :func:`time.monotonic`, grades it, and prints friendly
  feedback plus a compact status line; and
* a non-interactive ``--auto`` **simulation** mode that runs a synthetic
  student for ``N`` trials (answering correctly with probability tied to the
  engine's predicted success ``E``) and prints a concise trace and summary.

Only the Python standard library and the ``math_practice`` engine are used.
All state is in memory; nothing is persisted.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from math_practice import EngineConfig, PracticeEngine, TrialResult


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _format_problem(a: int, b: int, op: str = "+") -> str:
    """Render a problem prompt, e.g. ``"  7 + 2 = ?"``."""
    return f"  {a} {op} {b} = ?"


def _status_line(engine: PracticeEngine, result: TrialResult) -> str:
    """Compact status line: theta, predicted success E, mastery progress."""
    return (
        f"    [theta={result.theta_after:+.2f}  "
        f"E={result.E:.2f}  "
        f"mastered {engine.mastered_count()} / {engine.total()}]"
    )


def _feedback_line(result: TrialResult) -> str:
    """Friendly correct/incorrect feedback with score and time."""
    if result.correct and result.s > 0:
        mark = "Correct!"
    else:
        mark = "Not quite."
    return f"  {mark}  (score s={result.s:.2f}, time={result.response_time:.1f}s)"


# --------------------------------------------------------------------------- #
# Interactive mode
# --------------------------------------------------------------------------- #
def _read_answer(prompt: str) -> tuple[str, float]:
    """Show ``prompt`` and read one line, measuring elapsed wall time.

    Returns:
        ``(raw_text, elapsed_seconds)``. On EOF the raw text is the sentinel
        ``"q"`` so the caller treats it as a quit request.
    """
    start = time.monotonic()
    try:
        raw = input(prompt)
    except EOFError:
        return "q", time.monotonic() - start
    return raw, time.monotonic() - start


def _grade_input(raw: str, expected: int, elapsed: float, time_limit: float) -> bool:
    """Decide correctness of a raw answer, gracefully (spec: blank/slow/bad = wrong).

    Blank, non-numeric, or over-the-time-limit answers count as incorrect.
    """
    if elapsed >= time_limit:
        return False
    text = raw.strip()
    if not text:
        return False
    try:
        value = int(text)
    except ValueError:
        return False
    return value == expected


def _print_stats(engine: PracticeEngine, history: list[TrialResult]) -> None:
    """Print a session summary: theta, mastered count, recent history."""
    print()
    print("  ===== Stats =====")
    print(f"  theta    : {engine.theta:+.3f}")
    print(f"  mastered : {engine.mastered_count()} / {engine.total()}")
    print(f"  trials   : {len(history)}")
    if history:
        recent = history[-5:]
        print("  recent   :")
        for r in recent:
            outcome = "ok " if (r.correct and r.s > 0) else "x  "
            print(
                f"    {outcome} {str(r.exercise):>9}  "
                f"s={r.s:.2f}  t={r.response_time:4.1f}s  "
                f"theta->{r.theta_after:+.2f}"
            )
    print("  =================")
    print()


def run_interactive(engine: PracticeEngine) -> int:
    """Run the interactive practice loop until the child quits.

    Commands: ``q`` quits, ``stats`` prints a summary. Everything else is
    treated as an answer to the current problem.
    """
    cfg = engine.config
    history: list[TrialResult] = []

    print("Math practice! Type a number to answer.")
    print("Type 'stats' for your progress, or 'q' to quit.\n")

    celebrated = False
    while True:
        exercise = engine.next_exercise()
        expected = exercise.a + exercise.b
        prompt = _format_problem(exercise.a, exercise.b, exercise.op) + " "

        raw, elapsed = _read_answer(prompt)
        command = raw.strip().lower()

        if command == "q":
            print("\nGreat work today. Bye!")
            break
        if command == "stats":
            _print_stats(engine, history)
            continue

        correct = _grade_input(raw, expected, elapsed, cfg.TIME_LIMIT)
        result = engine.submit(exercise, correct, elapsed)
        history.append(result)

        print(_feedback_line(result))
        print(_status_line(engine, result))

        if engine.all_mastered() and not celebrated:
            print("\n  *** Amazing! You've mastered everything! ***")
            print("  (You can keep playing or type 'q' to stop.)\n")
            celebrated = True
        print()

    _print_stats(engine, history)
    return 0


# --------------------------------------------------------------------------- #
# Auto / simulation mode
# --------------------------------------------------------------------------- #
def _simulate_response_time(correct: bool, rng: random.Random, cfg: EngineConfig) -> float:
    """Generate a plausible response time for a synthetic student (seconds).

    Correct answers tend to be faster; incorrect ones a bit slower. The time
    is clamped to ``(0, TIME_LIMIT)`` so it never accidentally triggers the
    timeout path for a "correct" answer.
    """
    if correct:
        t = rng.uniform(1.0, 10.0)
    else:
        t = rng.uniform(4.0, 16.0)
    # Keep strictly inside the open interval the engine expects.
    return max(0.1, min(t, cfg.TIME_LIMIT - 0.1))


def run_auto(engine: PracticeEngine, n: int, rng: random.Random) -> int:
    """Run ``n`` simulated trials by a synthetic student and summarise.

    The student answers correctly with probability equal to the item's
    predicted success ``E`` at the current ability, with random plausible
    response times. A concise per-trial trace is printed, followed by a final
    summary including the theta trajectory and mastered count.
    """
    cfg = engine.config
    print(f"# auto simulation: {n} trials  (theta0={engine.theta:+.3f})\n")

    theta_trajectory: list[float] = [engine.theta]
    correct_count = 0

    for i in range(1, n + 1):
        exercise = engine.next_exercise()

        # Predicted success E at the current theta drives the student's skill.
        # Recompute E the same way the engine does, so the probability the
        # student is correct matches the item's predicted success.
        b = engine._scorer.score(exercise)  # noqa: SLF001 - intentional reuse of public formula
        E = engine._ability.expected_success(b)  # noqa: SLF001

        correct = rng.random() < E
        response_time = _simulate_response_time(correct, rng, cfg)

        result = engine.submit(exercise, correct, response_time)
        theta_trajectory.append(result.theta_after)
        if result.correct and result.s > 0:
            correct_count += 1

        mark = "ok" if (result.correct and result.s > 0) else "x "
        print(
            f"{i:3d}. {str(exercise):>9} = {exercise.a + exercise.b:<3d} "
            f"{mark}  E={result.E:.2f}  s={result.s:.2f}  "
            f"t={result.response_time:4.1f}s  "
            f"theta {result.theta_before:+.2f}->{result.theta_after:+.2f}  "
            f"mastered {engine.mastered_count()}/{engine.total()}"
        )

    print()
    print("# ===== summary =====")
    print(f"# trials       : {n}")
    print(f"# correct      : {correct_count} ({100.0 * correct_count / n:.0f}%)")
    print(f"# theta start  : {theta_trajectory[0]:+.3f}")
    print(f"# theta end    : {theta_trajectory[-1]:+.3f}")
    print(f"# theta min/max: {min(theta_trajectory):+.3f} / {max(theta_trajectory):+.3f}")
    print(f"# mastered     : {engine.mastered_count()} / {engine.total()}")
    print(f"# all mastered : {engine.all_mastered()}")
    print("# ===================")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="math-practice",
        description="Adaptive math practice for young learners (addition facts).",
    )
    parser.add_argument(
        "--auto",
        type=int,
        metavar="N",
        default=None,
        help="run N simulated trials by a synthetic student (non-interactive).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        metavar="S",
        default=None,
        help="seed the RNG for deterministic behaviour.",
    )
    parser.add_argument(
        "--max-sum",
        type=int,
        metavar="M",
        default=None,
        help="override the curriculum's maximum sum (a + b <= M).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Console entry point for the ``math-practice`` command."""
    args = _build_parser().parse_args(argv)

    rng = random.Random(args.seed) if args.seed is not None else random.Random()

    if args.max_sum is not None:
        config = EngineConfig(MAX_SUM=args.max_sum)
    else:
        config = EngineConfig()

    engine = PracticeEngine(config=config, rng=rng)

    if args.auto is not None:
        if args.auto <= 0:
            print("--auto requires a positive number of trials.", file=sys.stderr)
            return 2
        return run_auto(engine, args.auto, rng)

    try:
        return run_interactive(engine)
    except KeyboardInterrupt:
        print("\nBye!")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
