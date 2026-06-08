"""Postgres-native behavior that SQLite could not validate.

These tests assert the four production-only guarantees of the Postgres-first
schema (baseline migration ``d8efed1e2877``) that an in-memory SQLite test run
silently could not exercise:

    * **CITEXT** — ``users.email`` is case-insensitive.
    * **ENUM** — ``sessions.mode`` / ``sessions.status`` are native enum types
      that reject out-of-range values at the database level.
    * **FK CASCADE** — deleting a ``sessions`` row cascades to its ``trials`` /
      ``session_mastery`` / ``session_exercises`` children.
    * **UUID** — id columns are native ``uuid``, while the repository round-trips
      them as canonical ``str`` (selectable by the string id).

They run against the per-test, rolled-back Postgres transaction provided by the
``session_factory`` fixture (and the session-scoped ``engine`` for type
introspection). Postgres-only; needs Docker or
``MATH_PRACTICE_TEST_DATABASE_URL``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _new_learner(db) -> str:
    """Insert a learner row (no owning user) and return its id."""
    learner_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO learners (id, user_id, created_at) "
            "VALUES (:id, NULL, :now)"
        ),
        {"id": learner_id, "now": _NOW},
    )
    return learner_id


def _new_session(db, learner_id: str, *, mode: str = "endless") -> str:
    """Insert a minimal active session for ``learner_id`` and return its id."""
    session_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO sessions ("
            "  id, learner_id, module_id, mode, status, created_at, started_at,"
            "  last_activity_at, expires_at, theta, config, trial_seq,"
            "  questions_done, correct_count, total_time"
            ") VALUES ("
            "  :id, :learner_id, 'add_10', :mode, 'active', :now, :now,"
            "  :now, :now, 0.0, '{}'::jsonb, 0, 0, 0, 0.0"
            ")"
        ),
        {"id": session_id, "learner_id": learner_id, "mode": mode, "now": _NOW},
    )
    return session_id


def test_citext_email_is_case_insensitive(session_factory: sessionmaker) -> None:
    """A mixed-case email inserts and is found by a lowercase query (CITEXT)."""
    with session_factory() as db:
        db.execute(
            text(
                "INSERT INTO users (id, email, created_at) "
                "VALUES (:id, :email, :now)"
            ),
            {"id": "uid-1", "email": "User@Example.com", "now": _NOW},
        )
        db.commit()

        found = db.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": "user@example.com"},
        ).scalar_one_or_none()
        assert found == "uid-1", "CITEXT email must match case-insensitively"


def test_enum_rejects_out_of_range_mode(session_factory: sessionmaker) -> None:
    """A raw INSERT with an invalid enum value is rejected by the DB."""
    with session_factory() as db:
        learner_id = _new_learner(db)
        with pytest.raises(DBAPIError):
            _new_session(db, learner_id, mode="not_a_mode")
            db.flush()


def test_enum_rejects_out_of_range_status(session_factory: sessionmaker) -> None:
    """Updating status to an out-of-range enum value is rejected by the DB."""
    with session_factory() as db:
        learner_id = _new_learner(db)
        session_id = _new_session(db, learner_id)
        db.flush()
        with pytest.raises(DBAPIError):
            db.execute(
                text("UPDATE sessions SET status = :s WHERE id = :id"),
                {"s": "not_a_status", "id": session_id},
            )
            db.flush()


def test_fk_cascade_deletes_children(session_factory: sessionmaker) -> None:
    """Deleting a session cascades to its trial/mastery/exercise children."""
    with session_factory() as db:
        learner_id = _new_learner(db)
        session_id = _new_session(db, learner_id)

        db.execute(
            text(
                "INSERT INTO trials ("
                "  session_id, seq, a, b, correct, response_time, s, e,"
                "  theta_before, theta_after, created_at"
                ") VALUES ("
                "  :sid, 1, 3, 4, true, 1.0, 0.5, 0.5, 0.0, 0.1, :now)"
            ),
            {"sid": session_id, "now": _NOW},
        )
        db.execute(
            text(
                "INSERT INTO session_mastery ("
                "  session_id, a, b, streak, faults, mastered"
                ") VALUES (:sid, 3, 4, 1, 0, false)"
            ),
            {"sid": session_id},
        )
        db.execute(
            text(
                "INSERT INTO session_exercises ("
                "  session_id, seq, a, b, op, level, given_answer, correct,"
                "  elapsed, created_at"
                ") VALUES (:sid, 1, 3, 4, '+', 1, 7, true, 1.0, :now)"
            ),
            {"sid": session_id, "now": _NOW},
        )
        db.commit()

        # Sanity: children exist before the delete.
        for table in ("trials", "session_mastery", "session_exercises"):
            count = db.execute(
                text(f"SELECT count(*) FROM {table} WHERE session_id = :sid"),
                {"sid": session_id},
            ).scalar_one()
            assert count == 1, f"{table} should have 1 child before delete"

        db.execute(
            text("DELETE FROM sessions WHERE id = :sid"), {"sid": session_id}
        )
        db.commit()

        # ON DELETE CASCADE removed every child.
        for table in ("trials", "session_mastery", "session_exercises"):
            count = db.execute(
                text(f"SELECT count(*) FROM {table} WHERE session_id = :sid"),
                {"sid": session_id},
            ).scalar_one()
            assert count == 0, f"{table} child must be cascade-deleted"


# A fixed id reused by two tests below. Under the old shared-process in-memory
# SQLite DB this collided (duplicate PK on the second test); with per-test
# transaction rollback each test starts from an empty table, so both insert it
# cleanly. The two tests prove isolation.
_FIXED_LEARNER_ID = "00000000-0000-0000-0000-000000000001"


def _insert_fixed_learner(db) -> None:
    """Insert a learner with the shared :data:`_FIXED_LEARNER_ID`."""
    db.execute(
        text(
            "INSERT INTO learners (id, user_id, created_at) "
            "VALUES (:id, NULL, :now)"
        ),
        {"id": _FIXED_LEARNER_ID, "now": _NOW},
    )
    db.commit()


def test_isolation_same_id_first(session_factory: sessionmaker) -> None:
    """First test inserts a learner with a fixed PK (no collision)."""
    with session_factory() as db:
        _insert_fixed_learner(db)
        found = db.execute(
            text("SELECT count(*) FROM learners WHERE id = :id"),
            {"id": _FIXED_LEARNER_ID},
        ).scalar_one()
        assert found == 1


def test_isolation_same_id_second(session_factory: sessionmaker) -> None:
    """Second test reuses the SAME PK; rollback isolation means no collision."""
    with session_factory() as db:
        # If the previous test's write had leaked, this would raise a duplicate
        # primary-key IntegrityError. It does not — the DB is pristine.
        _insert_fixed_learner(db)
        found = db.execute(
            text("SELECT count(*) FROM learners WHERE id = :id"),
            {"id": _FIXED_LEARNER_ID},
        ).scalar_one()
        assert found == 1


def test_uuid_native_type_and_str_roundtrip(
    session_factory: sessionmaker,
) -> None:
    """Session id is native ``uuid`` yet selectable/round-trips as a str."""
    with session_factory() as db:
        learner_id = _new_learner(db)
        session_id = _new_session(db, learner_id)
        db.commit()

        # The column's runtime type is the native Postgres uuid.
        typ = db.execute(
            text("SELECT pg_typeof(id)::text FROM sessions WHERE id = :id"),
            {"id": session_id},
        ).scalar_one()
        assert typ == "uuid", f"sessions.id must be native uuid, got {typ!r}"

        # And it round-trips as the canonical string id we inserted with.
        round_tripped = db.execute(
            text("SELECT id::text FROM sessions WHERE id = :id"),
            {"id": session_id},
        ).scalar_one()
        assert round_tripped == session_id
        assert isinstance(session_id, str)
