"""Service-layer exceptions for the math-practice backend.

These exceptions are raised by :class:`~math_practice_backend.service.SessionService`
and translated to HTTP status codes by the API layer's exception handlers:

    * :class:`SessionNotFound`   -> 404
    * :class:`SessionExpired`    -> 410
    * :class:`NoPendingExercise` -> 409
    * :class:`InvalidConfig`     -> 422

They carry just enough context (the offending ``session_id`` and a human-readable
message) for handlers to build a useful response without leaking internals.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for all service-layer errors.

    Attributes:
        message: human-readable description of what went wrong.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SessionNotFound(ServiceError):
    """Raised when no session exists for the requested id.

    Attributes:
        session_id: the id that could not be found.
    """

    def __init__(self, session_id: str, message: str | None = None) -> None:
        super().__init__(message or f"Session not found: {session_id}")
        self.session_id = session_id


class SessionExpired(ServiceError):
    """Raised when a session exists but its retention window has elapsed.

    The session is deleted as a side effect of detection.

    Attributes:
        session_id: the id of the expired session.
    """

    def __init__(self, session_id: str, message: str | None = None) -> None:
        super().__init__(message or f"Session expired: {session_id}")
        self.session_id = session_id


class NoPendingExercise(ServiceError):
    """Raised when an answer is submitted but no exercise is pending.

    Attributes:
        session_id: the id of the session with no pending exercise.
    """

    def __init__(self, session_id: str, message: str | None = None) -> None:
        super().__init__(
            message or f"No pending exercise for session: {session_id}"
        )
        self.session_id = session_id


class InvalidConfig(ServiceError):
    """Raised when session-creation config overrides are unknown or invalid.

    Attributes:
        message: description of the offending override(s).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
