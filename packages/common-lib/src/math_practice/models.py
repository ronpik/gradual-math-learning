"""Domain models and curriculum construction (adaptive-practice-spec v1).

Defines the :class:`Exercise` value object and :func:`build_curriculum`, the
deterministic generator of the addition fact pool.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Exercise:
    """A single arithmetic exercise, e.g. ``7 + 2`` (spec v1).

    Immutable and hashable so exercises can serve as dictionary keys in the
    ability and mastery trackers.

    Attributes:
        a:  first operand (>= 1 in the standard curriculum).
        b:  second operand (>= 1 in the standard curriculum).
        op: binary operator symbol; defaults to ``"+"``.
    """

    a: int
    b: int
    op: str = "+"

    def __str__(self) -> str:
        """Render as ``"a op b"`` (e.g. ``"7 + 2"``)."""
        return f"{self.a} {self.op} {self.b}"


def build_curriculum(max_sum: int) -> list[Exercise]:
    """Build the ordered addition curriculum (spec v1).

    Returns every ordered pair ``(a, b)`` with ``a >= 1``, ``b >= 1`` and
    ``a + b <= max_sum``. Both orderings are included (``(2, 3)`` and
    ``(3, 2)`` are distinct exercises).

    The order is stable and deterministic: ascending by ``a``, then by ``b``.

    Args:
        max_sum: inclusive upper bound on ``a + b``.

    Returns:
        The curriculum as a list of :class:`Exercise` objects.
    """
    exercises: list[Exercise] = []
    for a in range(1, max_sum):
        for b in range(1, max_sum - a + 1):
            exercises.append(Exercise(a=a, b=b))
    return exercises
