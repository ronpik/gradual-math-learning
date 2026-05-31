"""Background expiry sweeper.

A small async loop that periodically purges sessions whose sliding retention
window has elapsed. It calls
:meth:`~math_practice_backend.repositories.SessionRepository.purge_expired`
every ``settings.sweeper_interval_seconds`` seconds, using the injected
:class:`~math_practice_backend.clock.Clock` for "now".

The loop is cancellable: cancelling the task (on application shutdown) breaks
the sleep and exits cleanly. ``purge_expired`` failures are swallowed and logged
so one bad sweep cannot kill the loop.
"""

from __future__ import annotations

import asyncio
import logging

from .clock import Clock
from .repositories import SessionRepository

logger = logging.getLogger(__name__)


async def sweeper_loop(
    repo: SessionRepository,
    clock: Clock,
    interval_seconds: float,
) -> None:
    """Run the expiry-sweep loop until cancelled.

    Sleeps ``interval_seconds`` between sweeps. Each sweep calls
    :meth:`SessionRepository.purge_expired` with the current time. Cancellation
    (via :meth:`asyncio.Task.cancel`) propagates out of the sleep and ends the
    loop.

    Args:
        repo:             the session repository to purge through.
        clock:            source of aware-UTC "now".
        interval_seconds: delay between sweeps (seconds).
    """
    logger.info(
        "Expiry sweeper started (interval=%ss)", interval_seconds
    )
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                deleted = repo.purge_expired(clock.now())
                if deleted:
                    logger.info("Sweeper purged %d expired session(s)", deleted)
            except Exception:  # pragma: no cover - defensive, keep loop alive
                logger.exception("Expiry sweep failed; continuing")
    except asyncio.CancelledError:
        logger.info("Expiry sweeper stopped")
        raise
