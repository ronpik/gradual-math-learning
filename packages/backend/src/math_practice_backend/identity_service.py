"""Auth identity resolution + anonymous-progress merge.

Sits between the verified :class:`~math_practice_backend.auth.AuthIdentity` and
the durable :class:`~math_practice_backend.domain.Learner` an authenticated
caller plays as. Like the other services it receives only ABC repositories
(:class:`UserRepository`, :class:`LearnerRepository`) and exchanges domain
dataclasses + engine value objects — it imports neither Firebase nor SQLAlchemy.

Two operations:

    * :meth:`resolve_learner` — map an identity to (creating on first sight) the
      user's single learner, used to override ``body.learner_id`` on an
      authenticated ``POST /v1/play/sessions``.
    * :meth:`claim_anonymous` — fold an anonymous learner's cross-session
      progress into the user's account on first login: adopt it outright if the
      user has no learner yet, else merge per-module progress keeping the
      more-advanced state.
"""

from __future__ import annotations

from datetime import datetime

from math_practice import ExerciseMastery

from .auth import AuthIdentity
from .clock import Clock
from .domain import Learner, ModuleProgress
from .repositories import LearnerRepository, UserRepository


def _merge_mastery(
    base: list[ExerciseMastery], incoming: list[ExerciseMastery]
) -> list[ExerciseMastery]:
    """Union two mastery lists keyed by ``(a, b)``, keeping the better entry.

    For each exercise present in either list, the kept entry is the one that is
    more advanced: a ``mastered`` entry always wins; otherwise the one with the
    higher streak wins, with faults broken toward fewer faults. The result is
    sorted by ``(a, b)`` for determinism.
    """
    by_key: dict[tuple[int, int], ExerciseMastery] = {}
    for m in base:
        by_key[(m.a, m.b)] = m
    for m in incoming:
        key = (m.a, m.b)
        current = by_key.get(key)
        if current is None or _is_more_advanced(m, current):
            by_key[key] = m
    return [by_key[k] for k in sorted(by_key)]


def _is_more_advanced(
    candidate: ExerciseMastery, current: ExerciseMastery
) -> bool:
    """Return whether ``candidate`` is the more-advanced mastery of the two."""
    if candidate.mastered != current.mastered:
        return candidate.mastered
    if candidate.streak != current.streak:
        return candidate.streak > current.streak
    return candidate.faults < current.faults


class IdentityService:
    """Resolves auth identities to learners and merges anonymous progress.

    Receives the user and learner persistence boundaries as ABCs; performs no
    token verification itself (that is the :class:`AuthProvider`'s job).
    """

    def __init__(
        self,
        user_repo: UserRepository,
        learner_repo: LearnerRepository,
        clock: Clock,
    ) -> None:
        """Build the service.

        Args:
            user_repo:    the user-account persistence boundary.
            learner_repo: the learner/module-progress persistence boundary.
            clock:        the shared clock for create timestamps.
        """
        self._user_repo = user_repo
        self._learner_repo = learner_repo
        self._clock = clock

    def resolve_learner(self, identity: AuthIdentity) -> Learner:
        """Return the user's learner, creating user/learner on first sight.

        Ensures the :class:`~math_practice_backend.domain.User` exists, then
        returns the user's first learner if any, else mints a new learner linked
        to the user.

        Args:
            identity: the verified caller identity.

        Returns:
            The user's :class:`Learner`.
        """
        now = self._clock.now()
        user = self._user_repo.get_or_create(
            identity.uid, identity.email, now
        )
        learners = self._learner_repo.list_learners_for_user(user.id)
        if learners:
            return learners[0]
        return self._learner_repo.create_learner_for_user(user.id, now)

    def claim_anonymous(
        self, identity: AuthIdentity, anonymous_learner_id: str
    ) -> Learner:
        """Fold an anonymous learner's progress into the user's account.

        If the user has no learner yet, the anonymous learner is *adopted*
        (linked to the user) so all its progress and sessions carry over. If the
        user already has a learner, the anonymous learner's per-module progress
        is *merged* into the user's learner, keeping the more-advanced state per
        module (higher θ; mastery unioned keeping the better entry). Unknown
        ``anonymous_learner_id`` is a safe no-op.

        Args:
            identity:             the verified caller identity.
            anonymous_learner_id: the localStorage learner to claim.

        Returns:
            The user's :class:`Learner` (now carrying the merged progress).
        """
        now = self._clock.now()
        user = self._user_repo.get_or_create(
            identity.uid, identity.email, now
        )

        anon = self._learner_repo.get(anonymous_learner_id)
        existing = self._learner_repo.list_learners_for_user(user.id)

        # No learner yet: adopt the anonymous one outright (carries sessions too).
        if not existing:
            if anon is not None and anon.user_id is None:
                self._learner_repo.link_learner_to_user(anon.id, user.id)
                refreshed = self._learner_repo.get(anon.id)
                return refreshed if refreshed is not None else anon
            # Anonymous learner unknown or already owned: mint a fresh learner.
            return self._learner_repo.create_learner_for_user(user.id, now)

        target = existing[0]

        # Unknown anon learner, or claiming the user's own learner: nothing to do.
        if anon is None or anon.id == target.id:
            return target

        self._merge_progress(anon.id, target.id, now)
        return target

    def _merge_progress(
        self, source_learner_id: str, target_learner_id: str, now: datetime
    ) -> None:
        """Merge every module the source learner has into the target learner."""
        for module_id in self._learner_repo.list_progress_modules(
            source_learner_id
        ):
            src = self._learner_repo.get_progress(
                source_learner_id, module_id
            )
            if src is None:
                continue
            dst = self._learner_repo.get_progress(
                target_learner_id, module_id
            )
            if dst is None:
                merged = ModuleProgress(
                    learner_id=target_learner_id,
                    module_id=module_id,
                    theta=src.theta,
                    mastery=list(src.mastery),
                    updated_at=now,
                )
            else:
                merged = ModuleProgress(
                    learner_id=target_learner_id,
                    module_id=module_id,
                    theta=max(dst.theta, src.theta),
                    mastery=_merge_mastery(dst.mastery, src.mastery),
                    updated_at=now,
                )
            self._learner_repo.save_progress(merged)
