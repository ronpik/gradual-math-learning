"""Pytest bootstrap: pin the backend to in-memory SQLite for tests.

The backend's settings load a developer ``.env.local`` (used to point a local
run at the docker-compose Postgres). Tests, however, must run against the
ephemeral in-memory SQLite database — independent of any developer's local DB
(see CLAUDE.md). Setting the env var here, before ``math_practice_backend`` is
imported, makes a real environment variable that takes precedence over the
``.env`` / ``.env.local`` files in pydantic-settings, so a bare ``pytest`` is
hermetic regardless of the developer's local configuration.
"""

from __future__ import annotations

import os

# Force the in-memory SQLite engine for the whole test session. Done at import
# time (conftest is loaded before the app and before Settings is first built).
os.environ["MATH_PRACTICE_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
