import asyncio
import hashlib

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.identity.factory import get_identity_repository, get_identity_service
from personal_markets.identity.testing import (
    admin_principal,
    bearer_for,
    invited_principal,
    make_principal,
)

TEST_SECRET = "phase1-test-secret-must-be-32b!!"


def _client(app=None) -> TestClient:
    return TestClient(app or isolated_app())


def test_allowlisted_admin_bootstraps_without_invitation() -> None:
    admin = make_principal("bootstrap-admin", email="admin@example.test", invited=False)
    other = invited_principal("owned-by-member")
    app = isolated_app()
    repo = get_identity_repository()
    repo.users[other.user_id] = other
    repo.by_clerk[other.clerk_user_id] = other.user_id
    app.state.auth_bypass_principal = None
    headers = {"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"}
    with TestClient(app) as client:
        created_goal = client.post(
            "/api/v1/agent/threads",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
            json={
                "kind": "create_goal",
                "intent": "I want to receive an SWE offer from a target company by August 2027.",
            },
        )
        assert created_goal.status_code == 200, created_goal.text
        thread_id = created_goal.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
            json={"confirmed": True},
        )
        assert resumed.status_code == 200, resumed.text
        goal_id = resumed.json()["goal"]["goal_id"]
        me = client.get("/api/v1/me", headers=headers)
        goals = client.get("/api/v1/goals", headers=headers)
        stolen = client.get(f"/api/v1/goals/{goal_id}", headers=headers)
        listed = client.get("/api/v1/admin/invites", headers=headers)
        created = client.post(
            "/api/v1/admin/invites",
            headers=headers,
            json={"note": "hackathon", "max_redemptions": 20},
        )
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "admin"
    assert body["invited"] is True
    assert body["hosted"]["enabled"] is True
    assert body["hosted"]["quota_usd"] == 100
    assert goals.status_code == 200
    assert goals.json() == []
    assert stolen.status_code == 404
    assert listed.status_code == 200
    assert listed.json() == []
    assert created.status_code == 200
    assert created.json()["max_redemptions"] == 20
    assert created.json()["token"]


def test_client_supplied_role_claim_is_ignored() -> None:
    from personal_markets.identity.tokens import issue_test_token

    token = issue_test_token(
        secret=TEST_SECRET,
        clerk_user_id="role-spoof",
        email="nobody@example.test",
        extra={"role": "admin"},
    )
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        goals = client.get("/api/v1/goals", headers={"Authorization": f"Bearer {token}"})
        invites = client.get("/api/v1/admin/invites", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "user"
    assert me.json()["invited"] is False
    assert goals.status_code == 403
    assert invites.status_code == 403


def test_unverified_allowlisted_email_is_not_admin() -> None:
    from personal_markets.identity.tokens import issue_test_token

    token = issue_test_token(
        secret=TEST_SECRET,
        clerk_user_id="unverified-admin",
        email="admin@example.test",
        email_verified=False,
    )
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        invites = client.get(
            "/api/v1/admin/invites", headers={"Authorization": f"Bearer {token}"}
        )
    assert me.json()["role"] == "user"
    assert invites.status_code == 403


def test_invitation_history_omits_plaintext_token() -> None:
    admin = admin_principal()
    app = isolated_app()
    _seed(app, admin)
    app.state.auth_bypass_principal = None
    headers = {"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/invites",
            headers=headers,
            json={"note": "history", "max_redemptions": 20},
        )
        listed = client.get("/api/v1/admin/invites", headers=headers)
        invitation_id = created.json()["invitation_id"]
        revoked = client.post(
            f"/api/v1/admin/invites/{invitation_id}/revoke",
            headers=headers,
        )
        listed_after = client.get("/api/v1/admin/invites", headers=headers)
    assert created.status_code == 200
    assert created.json()["token"]
    assert listed.status_code == 200
    assert listed.json()
    for item in listed.json():
        assert "token" not in item
    assert revoked.status_code == 200
    assert "token" not in revoked.json()
    for item in listed_after.json():
        assert "token" not in item


def test_health_is_public() -> None:
    with _client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert "database" not in response.json()


def test_goals_require_authentication() -> None:
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        response = client.get("/api/v1/goals")
    assert response.status_code == 401


def test_invalid_token_is_rejected() -> None:
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        response = client.get("/api/v1/goals", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_expired_token_is_rejected() -> None:
    from personal_markets.identity.tokens import issue_test_token

    token = issue_test_token(
        secret=TEST_SECRET,
        clerk_user_id="expired-user",
        email="expired@example.test",
        ttl_seconds=-10,
    )
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        response = client.get("/api/v1/goals", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_uninvited_user_cannot_list_goals() -> None:
    user = make_principal("uninvited")
    repo = get_identity_repository()
    repo.users[user.user_id] = user
    repo.by_clerk[user.clerk_user_id] = user.user_id
    app = isolated_app()
    repo = get_identity_repository()
    repo.users[user.user_id] = user
    repo.by_clerk[user.clerk_user_id] = user.user_id
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/goals", headers={"Authorization": f"Bearer {bearer_for(user, TEST_SECRET)}"}
        )
    assert response.status_code == 403


def test_cross_user_goal_access_is_hidden() -> None:
    owner = invited_principal("owner-a")
    other = invited_principal("owner-b")
    app = isolated_app()
    repo = get_identity_repository()
    for principal in (owner, other):
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/threads",
            headers={"Authorization": f"Bearer {bearer_for(owner, TEST_SECRET)}"},
            json={
                "kind": "create_goal",
                "intent": "I want to receive an SWE offer from a target company by August 2027.",
            },
        )
        assert created.status_code == 200, created.text
        thread_id = created.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume",
            headers={"Authorization": f"Bearer {bearer_for(owner, TEST_SECRET)}"},
            json={"confirmed": True},
        )
        assert resumed.status_code == 200, resumed.text
        goal_id = resumed.json()["goal"]["goal_id"]
        stolen = client.get(
            f"/api/v1/goals/{goal_id}",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
        )
        listed = client.get(
            "/api/v1/goals",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
        )
        evidence = client.get(
            f"/api/v1/goals/{goal_id}/evidence",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
        )
        history = client.get(
            f"/api/v1/what-if/history/{goal_id}",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
        )
        thread = client.get(
            f"/api/v1/agent/threads/{thread_id}",
            headers={"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"},
        )
    assert stolen.status_code == 404
    assert listed.status_code == 200
    assert listed.json() == []
    assert evidence.status_code == 404
    assert history.status_code == 404
    assert thread.status_code == 404


def test_invite_is_single_use_and_email_bound() -> None:
    admin = admin_principal()
    user = make_principal("invitee", email="invitee@example.test")
    stranger = make_principal("stranger", email="other@example.test")
    app = isolated_app()
    repo = get_identity_repository()
    for principal in (admin, user, stranger):
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"email": "invitee@example.test", "note": "judge"},
        )
        assert created.status_code == 200, created.text
        token = created.json()["token"]
        wrong = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(stranger, TEST_SECRET)}"},
            json={"token": token},
        )
        first = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(user, TEST_SECRET)}"},
            json={"token": token},
        )
        second = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(user, TEST_SECRET)}"},
            json={"token": token},
        )
        unauthenticated = client.post("/api/v1/admin/invites", json={"email": "x@example.test"})
        revoked_create = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"email": "later@example.test"},
        )
        invitation_id = revoked_create.json()["invitation_id"]
        revoked = client.post(
            f"/api/v1/admin/invites/{invitation_id}/revoke",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
        )
    assert wrong.status_code == 403
    assert first.status_code == 200
    assert first.json()["invited"] is True
    assert first.json()["hosted"]["enabled"] is True
    assert second.status_code == 403
    assert unauthenticated.status_code == 401
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None


async def test_invite_concurrent_redemption_is_single_winner() -> None:
    isolated_app()
    admin = admin_principal()
    first = make_principal("race-a", email="same@example.test")
    second = make_principal("race-b", email="same@example.test")
    repo = get_identity_repository()
    for principal in (admin, first, second):
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id
    identity = get_identity_service()
    invitation = await identity.create_invitation(admin, email="same@example.test")
    assert invitation.token is not None
    results = await asyncio.gather(
        identity.redeem_invitation(first, invitation.token),
        identity.redeem_invitation(second, invitation.token),
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, Exception)]
    assert len(successes) == 1
    token_hash = hashlib.sha256(invitation.token.encode("utf-8")).hexdigest()
    stored = await repo.get_invitation_by_hash(token_hash)
    assert stored is not None
    assert stored.redeemed_by is not None


def test_new_account_does_not_receive_hosted_inference() -> None:
    user = make_principal("fresh-user")
    app = isolated_app()
    repo = get_identity_repository()
    repo.users[user.user_id] = user
    repo.by_clerk[user.clerk_user_id] = user.user_id
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        me = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {bearer_for(user, TEST_SECRET)}"},
        )
    assert me.status_code == 200
    body = me.json()
    assert body["invited"] is False
    assert body["hosted"]["enabled"] is False


def _seed(app, *principals) -> None:
    del app
    repo = get_identity_repository()
    for principal in principals:
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id


def test_shared_invite_defaults_to_twenty_and_email_stays_single_use() -> None:
    admin = admin_principal()
    app = isolated_app()
    _seed(app, admin)
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        shared = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"note": "hackathon", "ttl_hours": 48, "max_redemptions": 20},
        )
        email_bound = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"email": "one@example.test", "max_redemptions": 20},
        )
    assert shared.status_code == 200, shared.text
    body = shared.json()
    assert body["kind"] == "shared"
    assert body["max_redemptions"] == 20
    assert body["redemption_count"] == 0
    assert body["token"]
    assert email_bound.status_code == 200
    assert email_bound.json()["kind"] == "email"
    assert email_bound.json()["max_redemptions"] == 1


def test_shared_invite_is_idempotent_and_caps_distinct_accounts() -> None:
    admin = admin_principal()
    first = make_principal("shared-a")
    repeat = first
    extra = [make_principal(f"shared-{index}") for index in range(20)]
    app = isolated_app()
    _seed(app, admin, first, *extra)
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"note": "hackathon", "max_redemptions": 20},
        )
        token = created.json()["token"]
        first_redeem = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(repeat, TEST_SECRET)}"},
            json={"token": token},
        )
        second_redeem = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(repeat, TEST_SECRET)}"},
            json={"token": token},
        )
        remaining = []
        for principal in extra:
            remaining.append(
                client.post(
                    "/api/v1/invites/redeem",
                    headers={"Authorization": f"Bearer {bearer_for(principal, TEST_SECRET)}"},
                    json={"token": token},
                ).status_code
            )
        listed = client.get(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
        )
        uninvited = make_principal("still-blocked")
        _seed(app, uninvited)
        blocked = client.get(
            "/api/v1/goals",
            headers={"Authorization": f"Bearer {bearer_for(uninvited, TEST_SECRET)}"},
        )
        hosted = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {bearer_for(repeat, TEST_SECRET)}"},
        )
    assert first_redeem.status_code == 200
    assert second_redeem.status_code == 200
    assert first_redeem.json()["hosted"]["quota_usd"] == second_redeem.json()["hosted"]["quota_usd"]
    assert remaining.count(200) == 19
    assert remaining[-1] == 403
    created_id = created.json()["invitation_id"]
    invite = next(item for item in listed.json() if item["invitation_id"] == created_id)
    assert "token" not in invite
    assert invite["redemption_count"] == 20
    assert invite["max_redemptions"] == 20
    assert blocked.status_code == 403
    assert hosted.json()["hosted"]["enabled"] is True


async def test_shared_invite_concurrent_distinct_accounts_consume_one_slot_each() -> None:
    isolated_app()
    admin = admin_principal()
    users = [make_principal(f"race-shared-{index}") for index in range(8)]
    repo = get_identity_repository()
    for principal in (admin, *users):
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id
    identity = get_identity_service()
    invitation = await identity.create_invitation(admin, max_redemptions=5)
    assert invitation.token is not None
    results = await asyncio.gather(
        *[identity.redeem_invitation(user, invitation.token) for user in users],
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, Exception)]
    assert len(successes) == 5
    stored = await repo.get_invitation_by_hash(
        hashlib.sha256(invitation.token.encode("utf-8")).hexdigest()
    )
    assert stored is not None
    assert stored.redemption_count == 5
    again = await identity.redeem_invitation(successes[0], invitation.token)
    stored_again = await repo.get_invitation_by_hash(
        hashlib.sha256(invitation.token.encode("utf-8")).hexdigest()
    )
    assert again.hosted_quota_usd == successes[0].hosted_quota_usd
    assert stored_again is not None
    assert stored_again.redemption_count == 5


def test_revoked_shared_invite_cannot_be_redeemed() -> None:
    admin = admin_principal()
    user = make_principal("after-revoke")
    app = isolated_app()
    _seed(app, admin, user)
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/invites",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
            json={"max_redemptions": 20},
        )
        invitation_id = created.json()["invitation_id"]
        token = created.json()["token"]
        revoked = client.post(
            f"/api/v1/admin/invites/{invitation_id}/revoke",
            headers={"Authorization": f"Bearer {bearer_for(admin, TEST_SECRET)}"},
        )
        denied = client.post(
            "/api/v1/invites/redeem",
            headers={"Authorization": f"Bearer {bearer_for(user, TEST_SECRET)}"},
            json={"token": token},
        )
    assert revoked.status_code == 200
    assert denied.status_code == 403
