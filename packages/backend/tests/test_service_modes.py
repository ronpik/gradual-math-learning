"""Plain-assert verification of :class:`SessionService` across practice modes.

Drives the service directly (no HTTP) against an isolated in-memory SQLite
database and a controllable :class:`FakeClock`, exercising the four locked
product decisions that live in the service: per-mode stop rules
(``FASTEST_20`` / ``THREE_MINUTE`` / ``ENDLESS``), op-aware server-side grading,
resume from written-through :class:`~math_practice_backend.domain.ModuleProgress`,
and the dual audit log.

Run directly (no pytest):

    uv run --package math-practice-backend \
        python packages/backend/tests/test_service_modes.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from math_practice import PracticeEngine, get_module

from math_practice_backend.db import Base
from math_practice_backend.enums import Mode, SessionStatus
from math_practice_backend.errors import SessionComplete
from math_practice_backend.repositories import (
    SqlAlchemyLearnerRepository,
    SqlAlchemySessionRepository,
)
from math_practice_backend.service import (
    ProgressService,
    SessionService,
    StatsService,
)


class FakeClock:
    """A :class:`~math_practice_backend.clock.Clock` with a settable ``now``.

    Time only advances when the test sets it, so deadline and TTL behaviour can
    be exercised deterministically.
    """

    def __init__(self, now: datetime) -> None:
        """Initialise the clock at ``now`` (an aware UTC datetime)."""
        self._now = now

    def now(self) -> datetime:
        """Return the currently-set time."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance the clock by ``seconds`` seconds."""
        self._now = self._now + timedelta(seconds=seconds)


class _Services(NamedTuple):
    """The split services plus the collaborators a test reaches into directly."""

    session: SessionService
    stats: StatsService
    progress: ProgressService
    repo: SqlAlchemySessionRepository
    learner_repo: SqlAlchemyLearnerRepository
    clock: FakeClock


def _build_service() -> _Services:
    """Build the isolated split services over a fresh in-memory SQLite database.

    Returns the session service, the read-only stats service, the progress
    service, the session repository (for direct audit-log reads), the learner
    repository (for direct progress reads), and the fake clock.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, future=True)

    repo = SqlAlchemySessionRepository(sf)
    learner_repo = SqlAlchemyLearnerRepository(sf)
    clock = FakeClock(datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc))
    progress_service = ProgressService(learner_repo)
    stats_service = StatsService(repo)
    service = SessionService(
        repo, progress_service, clock, ttl=timedelta(hours=24)
    )
    return _Services(
        session=service,
        stats=stats_service,
        progress=progress_service,
        repo=repo,
        learner_repo=learner_repo,
        clock=clock,
    )


def _expected(op: str, a: int, b: int) -> int:
    """Return the op-aware expected answer for ``a op b``."""
    return a + b if op == "+" else a - b


def test_fastest_20_completes_after_20() -> None:
    """FASTEST_20 stops after exactly 20 answers; the 21st draw is rejected."""
    svc = _build_service()
    service, stats = svc.session, svc.stats

    agg = service.create_session(None, "add_10", Mode.FASTEST_20)
    sid = agg.id
    learner_id = agg.learner_id
    assert learner_id, "create_session must return a learner id"
    assert agg.target_count == 20
    assert agg.target_seconds is None

    last_outcome = None
    for i in range(20):
        pending = service.get_next(sid)
        answer = _expected(pending.op, pending.a, pending.b)
        last_outcome = service.submit_answer(sid, answer, 1.5)
        if i < 19:
            assert not last_outcome.finished, f"answer {i + 1} should not finish"
        else:
            assert last_outcome.finished, "the 20th answer must finish the run"
        assert last_outcome.remaining["questions_left"] == 20 - (i + 1)

    # A 21st get_next must reject the now-complete run.
    raised = False
    try:
        service.get_next(sid)
    except SessionComplete:
        raised = True
    assert raised, "get_next after 20 answers must raise SessionComplete"

    summary = stats.get_summary(service.get_session(sid))
    assert summary.status is SessionStatus.COMPLETED
    assert "total_time_seconds" in summary.headline
    assert summary.headline["total_time_seconds"] == 20 * 1.5
    assert summary.questions_done == 20


def test_three_minute_deadline_rejects_late_answer() -> None:
    """THREE_MINUTE closes on the server deadline; in-window answers count."""
    svc = _build_service()
    service, stats, clock = svc.session, svc.stats, svc.clock

    agg = service.create_session(None, "sub_10", Mode.THREE_MINUTE)
    sid = agg.id
    assert agg.target_seconds == 180
    assert agg.target_count is None

    # Two in-window answers (subtraction, op-aware grading).
    for _ in range(2):
        clock.advance(2.0)
        pending = service.get_next(sid)
        assert pending.op == "-"
        answer = _expected(pending.op, pending.a, pending.b)
        outcome = service.submit_answer(sid, answer, 2.0)
        assert not outcome.finished
        assert outcome.trial.correct

    # Draw a third exercise still inside the window...
    pending = service.get_next(sid)
    answer = _expected(pending.op, pending.a, pending.b)

    # ...then advance the clock past the 180s deadline before answering.
    clock.advance(200.0)
    raised = False
    try:
        service.submit_answer(sid, answer, 1.0)
    except SessionComplete:
        raised = True
    assert raised, "an answer past the deadline must raise SessionComplete"

    # A subsequent get_next must also report completion.
    raised_next = False
    try:
        service.get_next(sid)
    except SessionComplete:
        raised_next = True
    assert raised_next, "get_next past the deadline must raise SessionComplete"

    summary = stats.get_summary(service.get_session(sid))
    assert summary.status is SessionStatus.COMPLETED
    # Only the two in-window answers counted; the late one was rejected.
    assert summary.headline["questions_done"] == 2
    assert summary.questions_done == 2


def test_endless_never_completes() -> None:
    """ENDLESS keeps drawing exercises no matter how many are answered."""
    svc = _build_service()
    service, stats = svc.session, svc.stats

    agg = service.create_session(None, "add_10", Mode.ENDLESS)
    sid = agg.id
    assert agg.target_count is None
    assert agg.target_seconds is None

    for _ in range(30):
        pending = service.get_next(sid)
        answer = _expected(pending.op, pending.a, pending.b)
        outcome = service.submit_answer(sid, answer, 1.0)
        assert not outcome.finished, "Endless must never finish"
        assert outcome.remaining == {}

    # get_next still serves an exercise after 30 answers.
    pending = service.get_next(sid)
    assert pending is not None
    summary = stats.get_summary(service.get_session(sid))
    assert summary.status is SessionStatus.ACTIVE
    assert "accuracy" in summary.headline


def test_resume_seeds_progress() -> None:
    """A second session for the same (learner, module) resumes raised θ."""
    svc = _build_service()
    service, learner_repo = svc.session, svc.learner_repo

    # First run: answer several correctly to raise θ above cold-start.
    first = service.create_session(None, "add_20", Mode.FASTEST_20)
    sid = first.id
    learner_id = first.learner_id
    for _ in range(8):
        pending = service.get_next(sid)
        answer = _expected(pending.op, pending.a, pending.b)
        service.submit_answer(sid, answer, 1.0)

    # Write-through must have persisted ModuleProgress for (learner, add_20).
    progress = learner_repo.get_progress(learner_id, "add_20")
    assert progress is not None, "ModuleProgress must be written through"

    # A cold-start engine for add_20 — the baseline θ to compare against.
    cold_theta = (
        PracticeEngine(config=get_module("add_20").build_config())
        .snapshot()
        .theta
    )
    assert progress.theta != cold_theta, (
        "resumable progress θ must differ from a fresh cold-start θ "
        f"(got {progress.theta}, cold {cold_theta})"
    )

    # A SECOND session for the same learner + module must seed (not cold-start).
    second = service.create_session(learner_id, "add_20", Mode.FASTEST_20)
    assert second.id != sid
    assert second.learner_id == learner_id
    assert second.engine_state.theta == progress.theta, (
        "the second session must seed θ from ModuleProgress, not cold-start"
    )
    assert second.engine_state.theta != cold_theta


def test_op_aware_grading() -> None:
    """Subtraction grades ``a - b`` correct and ``a + b`` wrong."""
    service = _build_service().session

    agg = service.create_session(None, "sub_10", Mode.ENDLESS)
    sid = agg.id

    # a - b is graded correct.
    pending = service.get_next(sid)
    assert pending.op == "-"
    correct_answer = pending.a - pending.b
    outcome = service.submit_answer(sid, correct_answer, 1.0)
    assert outcome.trial.correct, "a - b must be graded correct for subtraction"

    # a + b would be graded wrong (unless degenerate b == 0, which the pool
    # avoids for a real subtrahend; assert the op-aware miss explicitly).
    pending = service.get_next(sid)
    wrong_answer = pending.a + pending.b
    if pending.b == 0:
        wrong_answer = pending.a + 1  # guard against a degenerate 0 subtrahend
    outcome = service.submit_answer(sid, wrong_answer, 1.0)
    assert not outcome.trial.correct, (
        "a + b must be graded wrong for a subtraction module"
    )


def test_audit_log_one_row_per_answer() -> None:
    """The clean audit log gets one row per answer with the right op + level."""
    svc = _build_service()
    service, repo = svc.session, svc.repo

    agg = service.create_session(None, "sub_10", Mode.ENDLESS)
    sid = agg.id

    n = 6
    for _ in range(n):
        pending = service.get_next(sid)
        answer = _expected(pending.op, pending.a, pending.b)
        service.submit_answer(sid, answer, 1.0)

    rows = repo.list_session_exercises(sid)
    assert len(rows) == n, f"expected {n} audit rows, got {len(rows)}"
    for i, row in enumerate(rows, start=1):
        assert row.seq == i, "audit rows must be ordered by seq, 1-based"
        assert row.op == "-", "audit op must reflect the subtraction module"
        assert 1 <= row.level <= 5, f"audit level {row.level} out of 1..5"
        assert row.a - row.b == row.given_answer, (
            "audit row should record the op-aware correct answer we submitted"
        )


def main() -> None:
    """Run every service-mode assertion and print OK on success."""
    test_fastest_20_completes_after_20()
    test_three_minute_deadline_rejects_late_answer()
    test_endless_never_completes()
    test_resume_seeds_progress()
    test_op_aware_grading()
    test_audit_log_one_row_per_answer()
    print("OK - test_service_modes")


if __name__ == "__main__":
    main()
