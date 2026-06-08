"""Authentication boundary: ID-token verification behind an interface.

The service layer must never import Firebase / ``google-auth`` directly. It
speaks only :class:`AuthIdentity` (the verified ``uid`` + ``email``) and depends
on the :class:`AuthProvider` ABC, so the concrete verifier is swappable and
tests can inject a :class:`FakeAuthProvider`.

A failed verification raises :class:`AuthError`, mapped to ``401`` by the API
layer's exception handler (registered in :mod:`math_practice_backend.app`).

Two providers ship here:

    * :class:`FirebaseAuthProvider` — verifies a real Firebase ID token using
      the project id only (no service-account JSON), checking both audience and
      issuer.
    * :class:`FakeAuthProvider` — parses ``"fake:<uid>[:<email>]"`` tokens for
      tests and local development.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthIdentity:
    """A verified caller identity.

    The only thing the service layer ever sees of authentication: the stable
    ``uid`` (the :class:`~math_practice_backend.domain.User` id) and the
    caller's email, if the token carried one.

    Attributes:
        uid:   the verified user id (Firebase uid).
        email: the verified email, or ``None`` if absent from the token.
    """

    uid: str
    email: str | None = None


class AuthError(Exception):
    """Raised when an auth token is missing context, invalid, or expired.

    Mapped to ``401 Unauthorized`` by the API layer's exception handler.

    Attributes:
        message: human-readable description of the failure.
    """

    def __init__(self, message: str = "Invalid or expired token") -> None:
        super().__init__(message)
        self.message = message


class AuthProvider(abc.ABC):
    """Persistence-free boundary for verifying a bearer token.

    Implementations turn an opaque token string into an :class:`AuthIdentity`,
    or raise :class:`AuthError`. They never touch the repository/service layers.
    """

    @abc.abstractmethod
    def verify(self, token: str) -> AuthIdentity:
        """Verify ``token`` and return the caller's :class:`AuthIdentity`.

        Raises:
            AuthError: if the token is missing, malformed, invalid, or expired.
        """


class FirebaseAuthProvider(AuthProvider):
    """Verifies Firebase ID tokens using the project id only.

    Uses ``google.oauth2.id_token.verify_firebase_token`` with the project id as
    the expected audience, and additionally asserts the issuer is
    ``https://securetoken.google.com/<project_id>``. The verified ``user_id`` /
    ``sub`` claim becomes the uid; ``email`` is carried through when present. No
    service-account credentials are required — the verifier fetches Google's
    public signing keys over HTTPS.
    """

    def __init__(self, project_id: str) -> None:
        """Bind the provider to a Firebase project id.

        Args:
            project_id: the Firebase project id (token audience + issuer suffix).
        """
        self._project_id = project_id

    def verify(self, token: str) -> AuthIdentity:
        """Verify a Firebase ID token, returning its :class:`AuthIdentity`."""
        # Imported lazily so the module imports without google-auth installed
        # and so the service layer never pulls Firebase in transitively.
        try:
            import google.auth.transport.requests
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise AuthError("Firebase verification unavailable") from exc

        try:
            request = google.auth.transport.requests.Request()
            claims = google_id_token.verify_firebase_token(
                token, request, audience=self._project_id
            )
        except Exception as exc:  # ValueError, expired, transport errors, ...
            raise AuthError("Invalid or expired token") from exc

        if not claims:
            raise AuthError("Invalid token")

        expected_iss = f"https://securetoken.google.com/{self._project_id}"
        if claims.get("iss") != expected_iss:
            raise AuthError("Invalid token issuer")

        uid = claims.get("user_id") or claims.get("sub")
        if not uid:
            raise AuthError("Token missing subject")

        email = claims.get("email")
        return AuthIdentity(uid=uid, email=email)


class FakeAuthProvider(AuthProvider):
    """Parses ``"fake:<uid>[:<email>]"`` tokens for tests and local dev.

    Never contacts a network. Any token not of the expected form raises
    :class:`AuthError`, so the required-auth 401 paths are exercised exactly as
    with the real provider.
    """

    _PREFIX = "fake:"

    def verify(self, token: str) -> AuthIdentity:
        """Parse a fake token into an :class:`AuthIdentity`."""
        if not token or not token.startswith(self._PREFIX):
            raise AuthError("Invalid fake token")
        rest = token[len(self._PREFIX):]
        parts = rest.split(":", 1)
        uid = parts[0]
        if not uid:
            raise AuthError("Fake token missing uid")
        email = parts[1] if len(parts) == 2 and parts[1] else None
        return AuthIdentity(uid=uid, email=email)
