"""Plain-assert verification of the student-safe ``/v1/play`` HTTP surface.

Exercises the play API end-to-end through a :class:`fastapi.testclient.TestClient`
opened as a context manager (so the app **lifespan** runs and the schema is
created), and — the critical guarantee — asserts that *no* ``/v1/play`` response
ever leaks an engine internal (``theta``, ``mastered_count``, ``total``, the
per-trial score ``s``, or predicted success ``E``).

Run directly (no pytest):

    uv run --package math-practice-backend \
        python packages/backend/tests/test_play_api.py
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from math_practice_backend.app import app

# Engine internals that must never appear in any /v1/play response body.
_FORBIDDEN_KEYS = {"theta", "mastered_count", "total", "s", "E"}

# The single sanctioned exception: a summary's per-level entries are allowed to
# carry ``total`` (the per-level exercise count) alongside ``mastered`` — the
# locked product decision permits per-level (mastered, total) on the summary.
# These entries are pruned before the leak scan so that an *overall* ``total``
# (the engine-internal aggregate count) is still caught everywhere else.
_PER_LEVEL_KEYS = {"level", "mastered", "total"}


def _is_per_level_entry(payload: Any) -> bool:
    """Return whether ``payload`` is a sanctioned per-level completion entry."""
    return isinstance(payload, dict) and set(payload.keys()) == _PER_LEVEL_KEYS


def _assert_no_leak(payload: Any, where: str) -> None:
    """Assert no forbidden engine-internal key appears anywhere in ``payload``.

    Recurses into nested dicts and lists so a leak buried inside ``headline`` or
    ``levels`` is still caught. The only exception is a per-level completion
    entry (``{level, mastered, total}``), whose ``total`` is the per-level count
    the design explicitly permits on the summary.

    Args:
        payload: a decoded JSON value (dict/list/scalar).
        where:   a label identifying the response, for the failure message.
    """
    if _is_per_level_entry(payload):
        return
    if isinstance(payload, dict):
        leaked = _FORBIDDEN_KEYS & set(payload.keys())
        assert not leaked, f"{where} leaked engine internals: {sorted(leaked)}"
        for value in payload.values():
            _assert_no_leak(value, where)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_leak(item, where)


def test_play_api_flow_and_no_leak() -> None:
    """Walk the play flow and assert it works and never leaks internals."""
    with TestClient(app) as client:
        # GET /v1/play/modules -> the 6 modules.
        r_modules = client.get("/v1/play/modules")
        assert r_modules.status_code == 200, r_modules.text
        modules = r_modules.json()
        assert len(modules) == 6, f"expected 6 modules, got {len(modules)}"
        module_ids = {m["id"] for m in modules}
        assert module_ids == {
            "add_10",
            "add_20",
            "add_100",
            "sub_10",
            "sub_20",
            "sub_100",
        }
        _assert_no_leak(modules, "GET /v1/play/modules")

        # POST /v1/play/sessions -> 201 with a learner_id.
        r_create = client.post(
            "/v1/play/sessions",
            json={"module_id": "add_10", "mode": "fastest_20"},
        )
        assert r_create.status_code == 201, r_create.text
        session = r_create.json()
        assert session["learner_id"], "create must return a learner_id"
        sid = session["session_id"]
        assert session["module_id"] == "add_10"
        assert session["mode"] == "fastest_20"
        assert session["target_count"] == 20
        _assert_no_leak(session, "POST /v1/play/sessions")

        # POST .../next -> an exercise with op "+".
        r_next = client.post(f"/v1/play/sessions/{sid}/next")
        assert r_next.status_code == 200, r_next.text
        exercise = r_next.json()
        assert exercise["op"] == "+", "add_10 exercises must use op '+'"
        a, b = exercise["a"], exercise["b"]
        _assert_no_leak(exercise, "POST .../next")

        # POST .../answers -> correct + finished + questions_done.
        r_answer = client.post(
            f"/v1/play/sessions/{sid}/answers",
            json={"answer": a + b, "elapsed_seconds": 1.5},
        )
        assert r_answer.status_code == 200, r_answer.text
        answer = r_answer.json()
        assert answer["correct"] is True
        assert answer["finished"] is False
        assert answer["questions_done"] == 1
        assert answer["questions_left"] == 19
        _assert_no_leak(answer, "POST .../answers")

        # GET .../summary works (mid-run is fine; status still ACTIVE).
        r_summary = client.get(f"/v1/play/sessions/{sid}/summary")
        assert r_summary.status_code == 200, r_summary.text
        summary = r_summary.json()
        assert summary["module_id"] == "add_10"
        assert summary["mode"] == "fastest_20"
        assert "headline" in summary
        assert "levels" in summary
        # Per-level (mastered, total) IS allowed on the summary (locked decision).
        for entry in summary["levels"]:
            assert set(entry.keys()) == {"level", "mastered", "total"}
        _assert_no_leak(summary, "GET .../summary")

        # GET .../stats is also student-safe.
        r_stats = client.get(f"/v1/play/sessions/{sid}/stats")
        assert r_stats.status_code == 200, r_stats.text
        _assert_no_leak(r_stats.json(), "GET .../stats")


def main() -> None:
    """Run the play-API assertions and print OK on success."""
    test_play_api_flow_and_no_leak()
    print("OK - test_play_api")


if __name__ == "__main__":
    main()
