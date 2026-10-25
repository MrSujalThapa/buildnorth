from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.identity.domain import UserProfile
from personal_markets.identity.factory import get_identity_repository
from personal_markets.identity.testing import invited_principal


def _goal(title: str = "Land an FDE offer") -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title=title,
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={
            "event": "signed_offer",
            "description": "Receive and sign an FDE offer",
        },
        deadline=datetime.now(UTC) + timedelta(days=120),
        state_dimensions=["applications", "interviews"],
    )


def _register(principal) -> None:
    repo = get_identity_repository()
    repo.users[principal.user_id] = principal
    repo.by_clerk[principal.clerk_user_id] = principal.user_id


def test_private_market_is_not_guessable_or_listed() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("social-visitor")
    _register(visitor)
    goal = _goal()
    import asyncio

    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    with TestClient(app) as client:
        listed = client.get("/api/v1/public/markets")
        assert listed.status_code == 200
        assert listed.json()["items"] == []
        client.app.state.auth_bypass_principal = visitor
        hidden = client.get(f"/api/v1/public/markets/{goal.goal_id}")
        assert hidden.status_code == 404
        owner_only = client.get(f"/api/v1/goals/{goal.goal_id}")
        assert owner_only.status_code == 404
        vis = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility",
            json={"visibility": "public"},
        )
        assert vis.status_code == 404


def test_publish_star_follow_fork_and_revoke() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("social-visitor")
    _register(visitor)
    import asyncio

    asyncio.run(
        get_identity_repository().upsert_profile(
            owner.user_id, UserProfile(username="alice", display_name="Alice", bio="Builder")
        )
    )
    asyncio.run(
        get_identity_repository().upsert_profile(
            visitor.user_id, UserProfile(username="bob", display_name="Bob")
        )
    )
    goal = _goal()
    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    with TestClient(app) as client:
        preview = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility",
            json={"visibility": "public"},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["visibility"] == "public"
        assert (
            "email" not in str(body).lower()
            or "success" in body["public_preview"]["success_criteria"]
        )
        assert "token" not in body["public_preview"]["model_configuration"]
        listed = client.get("/api/v1/public/markets")
        assert any(item["goal_id"] == str(goal.goal_id) for item in listed.json()["items"])
        profile = client.get("/api/v1/public/profiles/alice")
        assert profile.status_code == 200
        assert profile.json()["creator"]["username"] == "alice"
        assert "radar" not in profile.json()
        share = client.get(f"/api/v1/social/markets/{goal.goal_id}/share")
        assert share.json()["shareable"] is True

        client.app.state.auth_bypass_principal = visitor
        public = client.get(f"/api/v1/public/markets/{goal.goal_id}")
        assert public.status_code == 200
        assert public.json()["title"] == goal.title
        star = client.post(f"/api/v1/social/markets/{goal.goal_id}/star")
        assert star.json()["star_count"] == 1
        again = client.post(f"/api/v1/social/markets/{goal.goal_id}/star")
        assert again.json()["star_count"] == 1
        follow = client.post("/api/v1/social/profiles/alice/follow")
        assert follow.json()["following"] is True
        follow_again = client.post("/api/v1/social/profiles/alice/follow")
        assert follow_again.json()["follower_count"] == 1
        self_follow = client.post("/api/v1/social/profiles/bob/follow")
        assert self_follow.status_code == 409
        forked = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/fork",
            json={"idempotency_key": "fork-retry-key-1", "title": "My FDE path"},
        )
        assert forked.status_code == 200
        fork_id = forked.json()["goal_id"]
        retry = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/fork",
            json={"idempotency_key": "fork-retry-key-1", "title": "My FDE path"},
        )
        assert retry.json()["goal_id"] == fork_id
        assert retry.json()["created"] is False
        mine = client.get(f"/api/v1/goals/{fork_id}")
        assert mine.status_code == 200
        assert mine.json()["title"] == "My FDE path"

        client.app.state.auth_bypass_principal = owner
        private = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility",
            json={"visibility": "private"},
        )
        assert private.json()["visibility"] == "private"
        client.app.state.auth_bypass_principal = visitor
        gone = client.get(f"/api/v1/public/markets/{goal.goal_id}")
        assert gone.status_code == 404
        still_listed = client.get("/api/v1/public/markets")
        assert still_listed.json()["items"] == []
        still_mine = client.get(f"/api/v1/goals/{fork_id}")
        assert still_mine.status_code == 200
        stars = client.get("/api/v1/public/profiles/bob/stars")
        assert stars.json()["items"] == []


def test_share_requires_public_visibility() -> None:
    app = isolated_app()
    goal = _goal("Run a sub-45-minute 10K")
    import asyncio

    asyncio.run(app.state.goal_repository.create(goal, app.state.auth_bypass_principal.user_id))
    with TestClient(app) as client:
        share = client.get(f"/api/v1/social/markets/{goal.goal_id}/share")
        assert share.json()["shareable"] is False
