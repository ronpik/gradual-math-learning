"""Verification of the Firebase-auth wiring on the ``/v1/play`` surface.

Drives the auth contract end-to-end through the pytest ``fake_auth`` fixture (a
:class:`fastapi.testclient.TestClient` with the :class:`AuthProvider` dependency
overridden by a :class:`~math_practice_backend.auth.FakeAuthProvider`, which
parses ``"fake:<uid>[:<email>]"`` tokens, so no network / real Firebase is
needed). Each test runs against an isolated, rolled-back Postgres transaction.
Covered:

    * an authenticated ``POST /v1/play/sessions`` uses the *user's* learner and
      ignores ``body.learner_id``;
    * ``GET /v1/play/me`` returns that same learner + email;
    * an anonymous run's progress is merged into the user's learner by
      ``POST /v1/play/claim`` — proven by the user's next authed session
      resuming the anonymous learner's θ;
    * required-auth routes return ``401`` with no token.

Run under pytest (Postgres-only; needs Docker or
``MATH_PRACTICE_TEST_DATABASE_URL``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from math_practice_backend.dependencies import get_learner_repository


def _auth(uid: str, email: str | None = None) -> dict[str, str]:
    """Build an ``Authorization`` header for the fake provider."""
    token = f"fake:{uid}"
    if email is not None:
        token = f"{token}:{email}"
    return {"Authorization": f"Bearer {token}"}


def test_authed_create_uses_users_learner_and_me(fake_auth: TestClient) -> None:
    """Authed create ignores body.learner_id; /me returns the user's learner."""
    client = fake_auth
    hdr = _auth("user-A", "a@example.com")

    # /me mints + returns the user's learner.
    r_me = client.get("/v1/play/me", headers=hdr)
    assert r_me.status_code == 200, r_me.text
    me = r_me.json()
    assert me["email"] == "a@example.com"
    user_learner = me["learner_id"]
    assert user_learner

    # Authed create with a bogus body.learner_id must IGNORE it and use the
    # user's learner.
    r_create = client.post(
        "/v1/play/sessions",
        headers=hdr,
        json={
            "learner_id": "some-other-anon-id",
            "module_id": "add_10",
            "mode": "endless",
        },
    )
    assert r_create.status_code == 201, r_create.text
    assert r_create.json()["learner_id"] == user_learner

    # /me is stable across calls (same learner).
    r_me2 = client.get("/v1/play/me", headers=hdr)
    assert r_me2.json()["learner_id"] == user_learner


def test_required_auth_routes_401_without_token(fake_auth: TestClient) -> None:
    """/me and /claim return 401 when no token is present."""
    client = fake_auth
    assert client.get("/v1/play/me").status_code == 401
    assert (
        client.post(
            "/v1/play/claim",
            json={"anonymous_learner_id": "whatever"},
        ).status_code
        == 401
    )
    # A present-but-invalid token is also 401.
    bad = {"Authorization": "Bearer not-a-fake-token"}
    assert client.get("/v1/play/me", headers=bad).status_code == 401


def test_claim_merges_anonymous_progress(fake_auth: TestClient) -> None:
    """Anonymous play then claim carries the anon learner's theta to the user."""
    client = fake_auth

    # 1) Anonymous run on add_10: create + answer some questions so the
    #    anonymous learner accrues non-trivial module progress (theta).
    r_anon = client.post(
        "/v1/play/sessions",
        json={"module_id": "add_10", "mode": "endless"},
    )
    assert r_anon.status_code == 201, r_anon.text
    anon_learner_id = r_anon.json()["learner_id"]
    anon_sid = r_anon.json()["session_id"]

    for _ in range(6):
        r_next = client.post(f"/v1/play/sessions/{anon_sid}/next")
        assert r_next.status_code == 200, r_next.text
        ex = r_next.json()
        client.post(
            f"/v1/play/sessions/{anon_sid}/answers",
            json={"answer": ex["a"] + ex["b"], "elapsed_seconds": 1.0},
        )

    learner_repo = get_learner_repository()
    anon_progress = learner_repo.get_progress(anon_learner_id, "add_10")
    assert anon_progress is not None
    anon_theta = anon_progress.theta

    # 2) First login for a brand-new user: the user has no learner yet, so claim
    #    ADOPTS the anonymous learner (progress carries over).
    hdr = _auth("user-claim", "claim@example.com")
    r_claim = client.post(
        "/v1/play/claim",
        headers=hdr,
        json={"anonymous_learner_id": anon_learner_id},
    )
    assert r_claim.status_code == 200, r_claim.text
    user_learner = r_claim.json()["learner_id"]

    # The adopted learner IS the anonymous one (its sessions carry too).
    assert user_learner == anon_learner_id

    # 3) A subsequent authed session for the user resumes the merged theta:
    #    seeding reads the user's-learner progress on add_10.
    user_progress = learner_repo.get_progress(user_learner, "add_10")
    assert user_progress is not None
    assert user_progress.theta == anon_theta


def test_claim_merges_into_existing_user_learner(fake_auth: TestClient) -> None:
    """When the user already has a learner, claim merges (keeps higher theta)."""
    client = fake_auth
    hdr = _auth("user-merge", "merge@example.com")
    learner_repo = get_learner_repository()

    # User already has a learner (via /me), with some add_10 progress.
    user_learner = client.get("/v1/play/me", headers=hdr).json()["learner_id"]
    r_u = client.post(
        "/v1/play/sessions",
        headers=hdr,
        json={"module_id": "add_10", "mode": "endless"},
    )
    u_sid = r_u.json()["session_id"]
    assert r_u.json()["learner_id"] == user_learner
    for _ in range(2):
        ex = client.post(f"/v1/play/sessions/{u_sid}/next").json()
        client.post(
            f"/v1/play/sessions/{u_sid}/answers",
            json={"answer": ex["a"] + ex["b"], "elapsed_seconds": 5.0},
        )
    user_theta_before = learner_repo.get_progress(user_learner, "add_10").theta

    # Separate anonymous learner with stronger add_10 progress (fast correct
    # answers -> higher theta).
    r_anon = client.post(
        "/v1/play/sessions",
        json={"module_id": "add_10", "mode": "endless"},
    )
    anon_learner_id = r_anon.json()["learner_id"]
    anon_sid = r_anon.json()["session_id"]
    assert anon_learner_id != user_learner
    for _ in range(8):
        ex = client.post(f"/v1/play/sessions/{anon_sid}/next").json()
        client.post(
            f"/v1/play/sessions/{anon_sid}/answers",
            json={"answer": ex["a"] + ex["b"], "elapsed_seconds": 0.5},
        )
    anon_theta = learner_repo.get_progress(anon_learner_id, "add_10").theta

    # Claim: user already has a learner -> MERGE, not adopt.
    r_claim = client.post(
        "/v1/play/claim",
        headers=hdr,
        json={"anonymous_learner_id": anon_learner_id},
    )
    assert r_claim.status_code == 200, r_claim.text
    assert r_claim.json()["learner_id"] == user_learner

    merged = learner_repo.get_progress(user_learner, "add_10")
    assert merged is not None
    assert merged.theta == max(user_theta_before, anon_theta)
