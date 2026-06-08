"""Application settings (pydantic-settings).

Centralises the few tunables the service needs at runtime. Values may be
overridden via environment variables (prefix ``MATH_PRACTICE_``) or a ``.env``
file. Switching storage from in-memory SQLite to file SQLite or Postgres is a
matter of changing :attr:`Settings.database_url` only.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the math-practice backend.

    Attributes:
        session_ttl_hours:        sliding retention window (hours) for a
                                  session, refreshed on every session-scoped
                                  request.
        sweeper_interval_seconds: how often the background sweeper purges
                                  expired sessions.
        database_url:             SQLAlchemy database URL. Defaults to a shared
                                  in-memory SQLite database (ephemeral).
        cors_allow_origins:       allowed CORS origins for browser clients.
                                  Defaults to ``["*"]`` (any origin).
        serve_web:                whether to mount the static web client at ``/``.
        web_dir:                  explicit path to the built web client; when
                                  ``None`` a repo-relative default is used.
        firebase_project_id:      the Firebase project id used to verify ID
                                  tokens (audience + issuer). ``None`` disables
                                  the live Firebase provider (tests inject a fake).
    """

    model_config = SettingsConfigDict(
        env_prefix="MATH_PRACTICE_",
        # Both files are optional; values in `.env.local` (machine-specific,
        # git-ignored) override `.env`, and real environment variables override
        # both. Missing files are ignored.
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    session_ttl_hours: int = 24
    sweeper_interval_seconds: int = 600
    database_url: str = "sqlite+pysqlite:///:memory:"
    cors_allow_origins: list[str] = ["*"]
    serve_web: bool = True
    web_dir: str | None = None
    firebase_project_id: str | None = "math-practice-498810"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, instantiated once."""
    return Settings()
