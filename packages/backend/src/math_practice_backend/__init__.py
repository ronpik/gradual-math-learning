"""math_practice_backend: HTTP backend for the adaptive math practice engine.

A thin FastAPI service that wraps the :mod:`math_practice` engine behind a REST
API. Sessions are persisted (SQLAlchemy 2.0 ORM, in-memory SQLite by default)
so a learner can resume an opaque ``session_id``; the server grades answers and
keeps a full trial log. Internal components exchange dataclasses; Pydantic is
used only at the HTTP edge.
"""

__version__ = "0.1.0"
