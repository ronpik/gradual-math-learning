"""httpx command-line client for the adaptive math-practice backend.

This module is a thin, dependency-light terminal client. It speaks to the
backend purely over HTTP (it never imports the engine or the backend packages)
using a single :class:`httpx.Client` bound to a ``base_url``.

It offers two modes:

* **Interactive practice** (default): create or resume a session, then loop
  drawing exercises, timing the user's answer locally with
  :func:`time.monotonic` (so network latency never eats into the mastery time
  budget), submitting the answer, and rendering friendly feedback plus mastery
  progress. The special inputs ``q`` (quit) and ``stats`` (show statistics) are
  recognised. The ``session_id`` is printed so the user can resume within the
  24h retention window via ``--session``.

* **Synthetic student** (``--auto N``): a deterministic, seeded robo-student
  that drives a *live* server over HTTP for ``N`` answers, printing a concise
  per-trial trace and a final summary. Given the same ``--seed`` (and server
  configuration) it produces identical behaviour, which makes it useful for
  smoke-testing and demos.

Resume semantics: when ``--session SID`` is supplied the client first tries to
``GET`` that session. If the server replies ``404`` (unknown) or ``410``
(expired) the client transparently creates a fresh session and tells the user.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"
"""Default base URL of the running backend."""

_QUIT_COMMANDS = frozenset({"q", "quit", "exit"})
_STATS_COMMANDS = frozenset({"stats", "s"})


# --------------------------------------------------------------------------- #
# Lightweight client-side views (decoded JSON, never the engine dataclasses).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Progress:
    """Client-side mirror of the server ``ProgressOut`` payload."""

    theta: float
    mastered_count: int
    total: int
    all_mastered: bool

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Progress":
        """Build a :class:`Progress` from a decoded ``ProgressOut`` mapping."""
        return cls(
            theta=float(data["theta"]),
            mastered_count=int(data["mastered_count"]),
            total=int(data["total"]),
            all_mastered=bool(data["all_mastered"]),
        )

    def render(self) -> str:
        """Return a one-line human-readable progress summary."""
        return (
            f"theta={self.theta:+.3f}  "
            f"mastered {self.mastered_count}/{self.total}"
        )


@dataclass(frozen=True)
class Exercise:
    """Client-side mirror of the server ``ExerciseOut`` payload."""

    a: int
    b: int
    op: str
    issued_at: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Exercise":
        """Build an :class:`Exercise` from a decoded ``ExerciseOut`` mapping."""
        return cls(
            a=int(data["a"]),
            b=int(data["b"]),
            op=str(data["op"]),
            issued_at=str(data["issued_at"]),
        )

    @property
    def prompt(self) -> str:
        """Return the rendered question, e.g. ``"3 + 4 = ?"``."""
        return f"{self.a} {self.op} {self.b} = ?"

    @property
    def expected(self) -> int:
        """Return the correct answer (the client knows the operands)."""
        # The backend only supports addition; the operator is informational.
        return self.a + self.b


# --------------------------------------------------------------------------- #
# HTTP API wrapper.
# --------------------------------------------------------------------------- #
class ApiClient:
    """Typed wrapper over the backend HTTP API using one :class:`httpx.Client`.

    Each method performs a single request, raises for HTTP error statuses, and
    returns the decoded JSON (or a small view object). Callers are expected to
    catch :class:`httpx.HTTPStatusError` where they need to special-case
    ``404`` / ``410`` (resume) or ``409`` (no pending exercise).
    """

    def __init__(self, client: httpx.Client) -> None:
        """Wrap an already-configured ``httpx.Client`` (with ``base_url`` set)."""
        self._client = client

    def health(self) -> dict[str, Any]:
        """GET ``/health`` -> decoded ``HealthOut``."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def create_session(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST ``/v1/sessions`` -> decoded ``SessionOut`` (201)."""
        body: dict[str, Any] | None = (
            {"config": overrides} if overrides else None
        )
        resp = self._client.post("/v1/sessions", json=body)
        resp.raise_for_status()
        return resp.json()

    def get_session(self, sid: str) -> dict[str, Any]:
        """GET ``/v1/sessions/{sid}`` -> decoded ``SessionOut``.

        Raises :class:`httpx.HTTPStatusError` on ``404`` (unknown) / ``410``
        (expired) so the caller can fall back to creating a fresh session.
        """
        resp = self._client.get(f"/v1/sessions/{sid}")
        resp.raise_for_status()
        return resp.json()

    def next_exercise(self, sid: str) -> Exercise:
        """POST ``/v1/sessions/{sid}/next`` -> :class:`Exercise`."""
        resp = self._client.post(f"/v1/sessions/{sid}/next")
        resp.raise_for_status()
        return Exercise.from_json(resp.json())

    def submit_answer(
        self, sid: str, answer: int, elapsed_seconds: float
    ) -> dict[str, Any]:
        """POST ``/v1/sessions/{sid}/answers`` -> decoded ``TrialOut``."""
        resp = self._client.post(
            f"/v1/sessions/{sid}/answers",
            json={"answer": answer, "elapsed_seconds": elapsed_seconds},
        )
        resp.raise_for_status()
        return resp.json()

    def stats(self, sid: str) -> dict[str, Any]:
        """GET ``/v1/sessions/{sid}/stats`` -> decoded ``StatsOut``."""
        resp = self._client.get(f"/v1/sessions/{sid}/stats")
        resp.raise_for_status()
        return resp.json()


def _is_status(exc: httpx.HTTPStatusError, *codes: int) -> bool:
    """Return True if ``exc`` carries one of the given HTTP status codes."""
    return exc.response.status_code in codes


# --------------------------------------------------------------------------- #
# Session acquisition (create vs. resume).
# --------------------------------------------------------------------------- #
def _acquire_session(
    api: ApiClient,
    resume_sid: str | None,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resume the requested session or create a new one.

    If ``resume_sid`` is given we attempt to fetch it; on ``404``/``410`` we
    fall back to creating a fresh session and tell the user. When no resume id
    is supplied we always create a new session.
    """
    if resume_sid:
        try:
            session = api.get_session(resume_sid)
            print(f"Resumed session {session['session_id']}.")
            return session
        except httpx.HTTPStatusError as exc:
            if _is_status(exc, 404, 410):
                reason = "expired" if exc.response.status_code == 410 else "unknown"
                print(
                    f"Session {resume_sid} is {reason}; starting a fresh one."
                )
            else:
                raise
    session = api.create_session(overrides)
    return session


# --------------------------------------------------------------------------- #
# Interactive mode.
# --------------------------------------------------------------------------- #
def _print_trial_feedback(trial: dict[str, Any]) -> None:
    """Render the graded result of one submitted answer."""
    progress = Progress.from_json(trial["progress"])
    verdict = "correct" if trial["correct"] else "wrong"
    answer = trial["a"] + trial["b"]
    print(
        f"  -> {verdict}!  (answer = {answer})  "
        f"score s={trial['s']:.2f}  E={trial['E']:.2f}  "
        f"theta {trial['theta_before']:+.3f} -> {trial['theta_after']:+.3f}"
    )
    print(f"  {progress.render()}")
    if progress.all_mastered:
        print("  All exercises mastered! Great job.")


def _print_stats(stats: dict[str, Any]) -> None:
    """Render aggregate session statistics with a recent-trials tail."""
    progress = Progress.from_json(stats["progress"])
    print("--- stats ---")
    print(
        f"  trials={stats['trials']}  correct={stats['correct']}  "
        f"accuracy={stats['accuracy'] * 100:.1f}%"
    )
    print(f"  {progress.render()}")
    recent = stats.get("recent") or []
    if recent:
        print("  recent (newest first):")
        for t in recent:
            mark = "OK " if t["correct"] else "X  "
            print(
                f"    #{t['seq']:<3} {mark} {t['a']} + {t['b']} "
                f"in {t['response_time']:.1f}s  E={t['E']:.2f}"
            )
    print("-------------")


def run_interactive(
    api: ApiClient,
    resume_sid: str | None,
    overrides: dict[str, Any] | None,
) -> int:
    """Run the interactive practice loop. Returns a process exit code."""
    session = _acquire_session(api, resume_sid, overrides)
    sid = session["session_id"]
    print(f"Session id: {sid}")
    print("Resume later within 24h with:  math-practice-client --session " + sid)
    print("Type your answer, 'stats' for statistics, or 'q' to quit.\n")

    while True:
        try:
            exercise = api.next_exercise(sid)
        except httpx.HTTPStatusError as exc:
            print(f"Could not fetch next exercise (HTTP {exc.response.status_code}).")
            return 1

        # Time the answer locally so network latency never counts against the
        # learner on the mastery time cutoff.
        start = time.monotonic()
        try:
            raw = input(f"{exercise.prompt} ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye! Resume with --session " + sid)
            return 0
        elapsed = time.monotonic() - start

        command = raw.strip().lower()
        if command in _QUIT_COMMANDS:
            print("Goodbye! Resume with --session " + sid)
            return 0
        if command in _STATS_COMMANDS:
            _print_stats(api.stats(sid))
            # The drawn exercise is still pending; the next loop re-shows it.
            continue

        try:
            answer = int(raw.strip())
        except ValueError:
            print("  Please enter a whole number, 'stats', or 'q'.")
            continue

        trial = api.submit_answer(sid, answer, elapsed)
        _print_trial_feedback(trial)
        if Progress.from_json(trial["progress"]).all_mastered:
            return 0
        print()


# --------------------------------------------------------------------------- #
# Synthetic-student (--auto) mode.
# --------------------------------------------------------------------------- #
def _synthetic_answer(
    exercise: Exercise, success_prob: float, rng: random.Random
) -> tuple[int, float]:
    """Decide a synthetic student's answer and a plausible elapsed time.

    With probability ``success_prob`` the student answers correctly; otherwise
    it returns a deliberately wrong answer (off by a small amount). Elapsed time
    is sampled from a plausible range that is shorter when confident. All
    randomness flows through ``rng`` for determinism.
    """
    correct = rng.random() < success_prob
    if correct:
        answer = exercise.expected
        # Confident answers are quicker; sample within the fast/mastery range.
        elapsed = rng.uniform(1.0, 6.0)
    else:
        delta = rng.choice([-2, -1, 1, 2])
        answer = exercise.expected + delta
        elapsed = rng.uniform(4.0, 12.0)
    return answer, round(elapsed, 2)


def run_auto(
    api: ApiClient,
    count: int,
    seed: int,
    overrides: dict[str, Any] | None,
) -> int:
    """Drive the server with a deterministic synthetic student.

    Plays ``count`` trials against a *live* server, printing a concise trace and
    a final summary. The robo-student's success probability for each item is
    derived from the predicted-success ``E`` returned by the *previous* trial
    (it starts optimistic), which loosely tracks the engine's own difficulty
    model. Determinism is guaranteed by seeding a local :class:`random.Random`.
    """
    rng = random.Random(seed)
    session = api.create_session(overrides)
    sid = session["session_id"]
    print(f"[auto] session id: {sid}  seed={seed}  trials={count}")

    success_prob = 0.85  # optimistic prior before we have an E estimate
    correct_total = 0
    last_progress: Progress | None = None

    for i in range(1, count + 1):
        try:
            exercise = api.next_exercise(sid)
        except httpx.HTTPStatusError as exc:
            print(f"[auto] aborted at trial {i}: HTTP {exc.response.status_code}")
            return 1

        answer, elapsed = _synthetic_answer(exercise, success_prob, rng)
        trial = api.submit_answer(sid, answer, elapsed)

        progress = Progress.from_json(trial["progress"])
        last_progress = progress
        if trial["correct"]:
            correct_total += 1
        mark = "OK " if trial["correct"] else "X  "
        print(
            f"[auto] #{i:<3} {exercise.a} + {exercise.b} "
            f"ans={answer} t={elapsed:>5.2f}s  {mark} "
            f"s={trial['s']:.2f} E={trial['E']:.2f} "
            f"theta={trial['theta_after']:+.3f}  "
            f"mastered {progress.mastered_count}/{progress.total}"
        )

        # Use the engine's predicted success E for this item as next prob; clamp
        # to keep the student plausibly capable.
        success_prob = min(0.98, max(0.55, float(trial["E"])))
        if progress.all_mastered:
            print(f"[auto] all mastered after {i} trials.")
            break

    accuracy = (correct_total / count) if count else 0.0
    print("[auto] --- summary ---")
    print(
        f"[auto] trials={count}  correct={correct_total}  "
        f"accuracy={accuracy * 100:.1f}%"
    )
    if last_progress is not None:
        print(
            f"[auto] final theta={last_progress.theta:+.3f}  "
            f"mastered {last_progress.mastered_count}/{last_progress.total}  "
            f"all_mastered={last_progress.all_mastered}"
        )
    print(f"[auto] session id: {sid}")
    return 0


# --------------------------------------------------------------------------- #
# CLI plumbing.
# --------------------------------------------------------------------------- #
def _build_overrides(args: argparse.Namespace) -> dict[str, Any] | None:
    """Collect engine config overrides from CLI flags (e.g. ``--max-sum``)."""
    overrides: dict[str, Any] = {}
    if args.max_sum is not None:
        overrides["MAX_SUM"] = args.max_sum
    return overrides or None


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the client CLI."""
    parser = argparse.ArgumentParser(
        prog="math-practice-client",
        description=(
            "Interactive httpx client for the adaptive math-practice backend. "
            "Practice addition facts, resume sessions within 24h, or run a "
            "deterministic synthetic student against a live server."
        ),
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Base URL of the backend (default: {DEFAULT_URL}).",
    )
    parser.add_argument(
        "--session",
        dest="session",
        metavar="SID",
        default=None,
        help="Resume an existing session id (created within the last 24h).",
    )
    parser.add_argument(
        "--auto",
        type=int,
        metavar="N",
        default=None,
        help="Run a deterministic synthetic student for N trials and exit.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for the --auto synthetic student (default: 0).",
    )
    parser.add_argument(
        "--max-sum",
        dest="max_sum",
        type=int,
        default=None,
        help="Override the engine MAX_SUM (largest a+b) for new sessions.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Parses args, opens one client, dispatches a mode."""
    args = build_parser().parse_args(argv)
    overrides = _build_overrides(args)

    try:
        with httpx.Client(base_url=args.url, timeout=30.0) as http:
            api = ApiClient(http)
            if args.auto is not None:
                if args.auto <= 0:
                    print("--auto N must be a positive integer.", file=sys.stderr)
                    return 2
                return run_auto(api, args.auto, args.seed, overrides)
            return run_interactive(api, args.session, overrides)
    except httpx.ConnectError:
        print(
            f"Could not connect to the backend at {args.url}. "
            "Is the server running?",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPStatusError as exc:
        print(
            f"Server returned HTTP {exc.response.status_code}: "
            f"{exc.response.text}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
