"""Time abstraction for the backend.

A tiny :class:`Clock` protocol lets time-dependent logic (TTL/expiry, trial
timestamps) be tested deterministically by injecting a fake clock, while
production uses :class:`RealClock`. All clocks return timezone-aware UTC
datetimes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of the current time as a timezone-aware UTC datetime."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC :class:`datetime`."""
        ...


class RealClock:
    """Wall-clock :class:`Clock` backed by the system clock (UTC)."""

    def now(self) -> datetime:
        """Return the current system time as an aware UTC :class:`datetime`."""
        return datetime.now(timezone.utc)
