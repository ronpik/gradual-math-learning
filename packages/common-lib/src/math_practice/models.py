"""Domain models and curriculum construction (adaptive-practice-spec v1).

Defines the :class:`Exercise` value object and :func:`build_curriculum`, the
deterministic generator of the addition or subtraction fact pool.
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


def build_curriculum(range_bound: int, op: str = "+") -> list[Exercise]:
    """Build the ordered curriculum for an operation (spec v1).

    The curriculum is the full, deterministic fact pool for ``op`` within
    ``range_bound``; the order is stable: ascending by ``a``, then by ``b``.

    For ``op == "+"`` returns every ordered pair ``(a, b)`` with ``a >= 1``,
    ``b >= 1`` and ``a + b <= range_bound`` (``range_bound`` bounds the sum).
    Both orderings are included (``(2, 3)`` and ``(3, 2)`` are distinct
    exercises).

    For ``op == "-"`` returns every pair ``(a, b)`` with minuend ``a`` in
    ``1..range_bound`` and subtrahend ``b`` in ``1..a`` (``range_bound`` bounds
    the minuend), so every exercise has a non-negative result ``a - b``.

    Args:
        range_bound: inclusive curriculum bound -- the sum bound for addition
            or the minuend bound for subtraction.
        op: binary operator symbol; ``"+"`` (default) or ``"-"``.

    Returns:
        The curriculum as a list of :class:`Exercise` objects.

    Raises:
        ValueError: if ``op`` is neither ``"+"`` nor ``"-"``.
    """
    exercises: list[Exercise] = []
    if op == "+":
        for a in range(1, range_bound):
            for b in range(1, range_bound - a + 1):
                exercises.append(Exercise(a=a, b=b, op="+"))
    elif op == "-":
        for a in range(1, range_bound + 1):
            for b in range(1, a + 1):
                exercises.append(Exercise(a=a, b=b, op="-"))
    else:
        raise ValueError(f"unknown op: {op!r}")
    return exercises
