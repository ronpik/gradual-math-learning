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
    """

    model_config = SettingsConfigDict(
        env_prefix="MATH_PRACTICE_",
        env_file=".env",
        extra="ignore",
    )

    session_ttl_hours: int = 24
    sweeper_interval_seconds: int = 600
    database_url: str = "sqlite+pysqlite:///:memory:"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, instantiated once."""
    return Settings()
