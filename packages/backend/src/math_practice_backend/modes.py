"""Practice-mode strategy — stop rule plus headline metric, nothing more.

A **mode** never changes which exercise the engine selects next; selection is the
85%-comfort softmax for every mode. A mode contributes exactly two things: a
server-enforced *stop rule* (when does this run end, and may a late answer still
be recorded) and a *headline metric* (the single number reported as the run's
result on the summary).

The service never branches on a mode string. It resolves the mode once via
:func:`get_mode` and asks the returned :class:`PracticeMode` strategy object the
questions it needs — :meth:`~PracticeMode.is_complete`,
:meth:`~PracticeMode.accepts_answer`, :meth:`~PracticeMode.remaining`,
:meth:`~PracticeMode.headline`. This keeps the three modes out of ``if/elif``
ladders in :class:`~math_practice_backend.service.SessionService`.

The three modes:

* **Fastest-20** stops after 20 answered; the headline is total wall time; the
  personal best is the minimum total time over completed sessions.
* **3-minute** stops at the server-authoritative deadline
  (``started_at + target_seconds``, 180s); an answer arriving at or past the
  deadline is rejected and the session is closed; the headline is the count of
  questions done; the best is the maximum count.
* **Endless** never stops; the headline is running accuracy; there is no best.

Mode objects hold no per-session state — they read everything they need from the
passed-in :class:`~math_practice_backend.domain.SessionAggregate` and the current
time — so each is a stateless singleton, registered once in :data:`MODES`.
"""

from __future__ import annotations

import abc
from datetime import timedelta
from typing import TYPE_CHECKING

from .enums import Mode
from .errors import UnknownMode

if TYPE_CHECKING:
    from datetime import datetime

    from .domain import SessionAggregate


# The 3-minute mode's deadline when an aggregate carries no explicit
# ``target_seconds`` (it always should; this is a defensive fallback).
_DEFAULT_TARGET_SECONDS = 180

# Fastest-20's fixed count target.
_FASTEST_20_TARGET = 20


class PracticeMode(abc.ABC):
    """A practice mode: a stop rule and a headline metric over a session.

    Strategy interface for the three modes. Every method is a pure function of
    the passed-in :class:`~math_practice_backend.domain.SessionAggregate` (and,
    where relevant, the current time); a mode instance carries no mutable state
    and is shared as a singleton.

    The ``remaining`` and ``headline`` return values are small ``dict`` payloads
    rather than typed value objects on purpose: their shape varies by mode (a
    count, a duration, or nothing), and they flow straight out to the
    student-safe summary without exposing any engine internals.
    """

    @abc.abstractmethod
    def target_count(self) -> int | None:
        """Return the number of answers required to complete, if count-bound.

        Returns:
            The count target (``20`` for Fastest-20), or ``None`` when the mode
            has no count target.
        """

    @abc.abstractmethod
    def target_seconds(self) -> int | None:
        """Return the run's duration in seconds, if time-bound.

        Returns:
            The duration target (``180`` for 3-minute), or ``None`` when the
            mode is untimed.
        """

    @abc.abstractmethod
    def is_complete(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether the mode's stop rule has been met.

        Args:
            agg: the session being evaluated.
            now: the current time (aware UTC).

        Returns:
            ``True`` when no further exercise should be served.
        """

    @abc.abstractmethod
    def accepts_answer(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether an answer arriving now may still be recorded.

        Distinct from :meth:`is_complete` for timed modes: an answer that
        arrives exactly at or past the deadline is *not* accepted even though the
        run only just completed.

        Args:
            agg: the session being evaluated.
            now: the current time (aware UTC).

        Returns:
            ``True`` when the answer should be graded and recorded.
        """

    @abc.abstractmethod
    def remaining(self, agg: SessionAggregate, now: datetime) -> dict:
        """Return what is left of the run, as a small mode-specific payload.

        Args:
            agg: the session being evaluated.
            now: the current time (aware UTC).

        Returns:
            ``{"questions_left": int}`` for a count-bound mode,
            ``{"seconds_left": float}`` for a time-bound mode, or ``{}`` when the
            mode is unbounded.
        """

    @abc.abstractmethod
    def headline(self, agg: SessionAggregate) -> dict:
        """Return the run's headline metric as a small mode-specific payload.

        Args:
            agg: the session being summarized.

        Returns:
            ``{"total_time_seconds": float}`` for Fastest-20,
            ``{"questions_done": int}`` for 3-minute, or ``{"accuracy": float}``
            for Endless.
        """


class Fastest20Mode(PracticeMode):
    """Race to answer 20 questions; the headline is total wall time.

    The run completes once 20 questions have been answered. Wrong answers cost
    wall time but carry no extra penalty. The personal best is the minimum total
    time over completed sessions (computed by the repository, not here).
    """

    def target_count(self) -> int | None:
        """Return ``20`` — the fixed number of answers to complete the run."""
        return _FASTEST_20_TARGET

    def target_seconds(self) -> int | None:
        """Return ``None`` — Fastest-20 is not time-bound."""
        return None

    def is_complete(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether 20 questions have been answered."""
        return agg.questions_done >= _FASTEST_20_TARGET

    def accepts_answer(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether the 20th answer has not yet been recorded."""
        return not self.is_complete(agg, now)

    def remaining(self, agg: SessionAggregate, now: datetime) -> dict:
        """Return ``{"questions_left": int}`` clamped at zero."""
        return {
            "questions_left": max(0, _FASTEST_20_TARGET - agg.questions_done)
        }

    def headline(self, agg: SessionAggregate) -> dict:
        """Return ``{"total_time_seconds": float}`` — the run's wall time."""
        return {"total_time_seconds": agg.total_time}


class ThreeMinuteMode(PracticeMode):
    """Answer as many as possible before a server-authoritative deadline.

    The deadline is ``started_at + target_seconds`` (180s), known at session
    creation. An answer that arrives at or past the deadline is rejected and the
    session is closed. The headline is the count of questions done; the best is
    the maximum count over completed sessions.
    """

    def target_count(self) -> int | None:
        """Return ``None`` — 3-minute has no count target."""
        return None

    def target_seconds(self) -> int | None:
        """Return ``180`` — the run's fixed duration in seconds."""
        return _DEFAULT_TARGET_SECONDS

    def _deadline(self, agg: SessionAggregate) -> datetime:
        """Return the run's deadline (``started_at + target_seconds``)."""
        seconds = agg.target_seconds or _DEFAULT_TARGET_SECONDS
        return agg.started_at + timedelta(seconds=seconds)

    def is_complete(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether the deadline has been reached."""
        return now >= self._deadline(agg)

    def accepts_answer(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return whether the answer arrived strictly before the deadline."""
        return now < self._deadline(agg)

    def remaining(self, agg: SessionAggregate, now: datetime) -> dict:
        """Return ``{"seconds_left": float}`` until the deadline, clamped."""
        seconds_left = (self._deadline(agg) - now).total_seconds()
        return {"seconds_left": max(0.0, seconds_left)}

    def headline(self, agg: SessionAggregate) -> dict:
        """Return ``{"questions_done": int}`` — the run's solved count."""
        return {"questions_done": agg.questions_done}


class EndlessMode(PracticeMode):
    """Practice without end; the headline is running accuracy.

    There is no stop rule and every answer is accepted. The headline is the
    fraction of correct answers so far (``0.0`` before any answer); there is no
    personal best.
    """

    def target_count(self) -> int | None:
        """Return ``None`` — Endless has no count target."""
        return None

    def target_seconds(self) -> int | None:
        """Return ``None`` — Endless is untimed."""
        return None

    def is_complete(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return ``False`` — Endless never completes on its own."""
        return False

    def accepts_answer(self, agg: SessionAggregate, now: datetime) -> bool:
        """Return ``True`` — Endless always accepts the next answer."""
        return True

    def remaining(self, agg: SessionAggregate, now: datetime) -> dict:
        """Return ``{}`` — there is nothing left to count down."""
        return {}

    def headline(self, agg: SessionAggregate) -> dict:
        """Return ``{"accuracy": float}`` — correct over answered, or ``0.0``."""
        if not agg.questions_done:
            return {"accuracy": 0.0}
        return {"accuracy": agg.correct_count / agg.questions_done}


MODES: dict[Mode, PracticeMode] = {
    Mode.FASTEST_20: Fastest20Mode(),
    Mode.THREE_MINUTE: ThreeMinuteMode(),
    Mode.ENDLESS: EndlessMode(),
}
"""The registered mode strategies, one stateless singleton per :class:`Mode`."""


def get_mode(mode: Mode) -> PracticeMode:
    """Resolve a :class:`Mode` to its :class:`PracticeMode` strategy singleton.

    Args:
        mode: the practice mode to resolve.

    Returns:
        The shared strategy instance for ``mode``.

    Raises:
        UnknownMode: if ``mode`` is not a registered practice mode.
    """
    try:
        return MODES[mode]
    except KeyError as exc:
        raise UnknownMode(str(mode)) from exc
