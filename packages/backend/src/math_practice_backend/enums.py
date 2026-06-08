"""Enumerations shared across the backend's session and play surfaces.

These string-valued enums are the backend's vocabulary for *which kind of run*
a session is (:class:`Mode`) and *where in its lifecycle* it sits
(:class:`SessionStatus`). They are plain ``str`` enums so they serialize to their
wire value transparently, persist as text in the ORM, and compare equal to the
bare string a client sends.

A **mode** never changes which exercise the engine selects next; it only adds a
server-enforced stop rule and the headline metric surfaced on the summary. The
status tracks the session through its 24h sliding lifetime.
"""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """A practice mode — a stop rule plus a headline metric, nothing more.

    Selection is identical across all modes (the 85%-comfort softmax); a mode
    only decides when a run ends and which number is reported as its result.

    Members:
        FASTEST_20:   stop after 20 answered; headline is total time, best is the
                      minimum total time over completed sessions.
        THREE_MINUTE: stop at the server deadline (``started_at + 180s``); headline
                      is the number of questions done, best is the maximum count.
        ENDLESS:      no stop rule; headline is running accuracy, no personal best.
    """

    FASTEST_20 = "fastest_20"
    THREE_MINUTE = "three_minute"
    ENDLESS = "endless"


class SessionStatus(str, Enum):
    """The lifecycle state of a practice session.

    Members:
        ACTIVE:    in progress; accepting next/answer requests.
        COMPLETED: the mode's stop rule was met; ``ended_at`` is set and the
                   session is immutable.
        EXPIRED:   the 24h sliding retention window elapsed before completion.
        ABANDONED: reclaimed by the background sweeper after inactivity without
                   completing.
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ABANDONED = "abandoned"
