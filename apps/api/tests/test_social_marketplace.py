from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.identity.domain import Principal, UserProfile
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


def _register(principal: Principal) -> None:
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
        app.state.auth_bypass_principal = visitor
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

        app.state.auth_bypass_principal = visitor
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

        app.state.auth_bypass_principal = owner
        private = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility",
            json={"visibility": "private"},
        )
        assert private.json()["visibility"] == "private"
        app.state.auth_bypass_principal = visitor
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


def test_public_heatmap_excludes_private_goal_activity() -> None:
    import asyncio

    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("heatmap-visitor")
    _register(visitor)
    asyncio.run(
        get_identity_repository().upsert_profile(
            owner.user_id, UserProfile(username="heatmap-owner", display_name="Owner")
        )
    )
    public_goal = _goal("Public training")
    private_goal = _goal("Private training")
    asyncio.run(app.state.goal_repository.create(public_goal, owner.user_id))
    asyncio.run(app.state.goal_repository.create(private_goal, owner.user_id))
    today = datetime.now(UTC).date()
    asyncio.run(
        app.state.social_repository.record_activity(
            owner.user_id, "evidence_accepted", today, public_goal.goal_id
        )
    )
    asyncio.run(
        app.state.social_repository.record_activity(
            owner.user_id, "evidence_accepted", today, private_goal.goal_id
        )
    )
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/v1/social/markets/{public_goal.goal_id}/visibility",
                json={"visibility": "public"},
            ).status_code
            == 200
        )
        own = client.get("/api/v1/public/profiles/heatmap-owner").json()
        assert own["contribution_total"] == 3
        app.state.auth_bypass_principal = visitor
        other = client.get("/api/v1/public/profiles/heatmap-owner").json()
        assert other["contribution_total"] == 2
        assert other["activity"][0]["count"] == 2
        app.state.auth_bypass_principal = owner
        assert (
            client.post(
                f"/api/v1/social/markets/{public_goal.goal_id}/visibility",
                json={"visibility": "private"},
            ).status_code
            == 200
        )
        app.state.auth_bypass_principal = visitor
        assert client.get("/api/v1/public/profiles/heatmap-owner").json()["contribution_total"] == 0


def test_fork_cannot_copy_private_source_contract_fields() -> None:
    from personal_markets.core.errors import ConflictError
    from personal_markets.social.blueprint import fork_goal

    source = _goal()
    source.resource_constraints.hours_per_week = 37
    source.success_definition = {"private_journal": "Sensitive details"}
    try:
        fork_goal(source, owner_title=None, deadline=None, new_goal_id=uuid4())
    except ConflictError:
        pass
    else:
        raise AssertionError("Fork copied private contract fields")

    source.success_definition = {"event": "signed_offer", "private_journal": "Sensitive details"}
    forked = fork_goal(source, owner_title=None, deadline=None, new_goal_id=uuid4())
    assert forked.success_definition == {"event": "signed_offer"}
    assert forked.resource_constraints.hours_per_week is None


def test_public_history_only_uses_published_forecasts() -> None:
    from personal_markets.social.blueprint import history_points

    stamp = datetime.now(UTC)
    rows = [
        {"source_kind": "published_forecast", "probability": 0.4, "created_at": stamp},
        {"source_kind": "synthetic_demo", "probability": 0.9, "created_at": stamp},
        {"source_kind": "scenario", "probability": 0.8, "created_at": stamp},
    ]
    assert [point.probability for point in history_points(rows)] == [0.4]


def test_public_search_pages_and_counts_track_filters() -> None:
    import asyncio

    app = isolated_app()
    owner = app.state.auth_bypass_principal
    goals = [_goal(f"Public journey {index:02d}") for index in range(27)]
    for goal in goals:
        asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    with TestClient(app) as client:
        for goal in goals:
            response = client.post(
                f"/api/v1/social/markets/{goal.goal_id}/visibility",
                json={"visibility": "public"},
            )
            assert response.status_code == 200
        first = client.get("/api/v1/public/markets", params={"limit": 24, "offset": 0}).json()
        second = client.get("/api/v1/public/markets", params={"limit": 24, "offset": 24}).json()
        assert first["total"] == second["total"] == 27
        assert first["limit"] == second["limit"] == 24
        assert [len(first["items"]), len(second["items"])] == [24, 3]
        ids = [item["goal_id"] for item in first["items"] + second["items"]]
        assert len(ids) == len(set(ids)) == 27
        assert client.post(f"/api/v1/social/markets/{goals[-1].goal_id}/star").status_code == 200
        most_starred = client.get(
            "/api/v1/public/markets", params={"sort": "stars", "limit": 24}
        ).json()
        assert most_starred["items"][0]["goal_id"] == str(goals[-1].goal_id)
        starred_next = client.get(
            "/api/v1/public/markets", params={"sort": "stars", "limit": 24, "offset": 24}
        ).json()
        starred_ids = [item["goal_id"] for item in most_starred["items"] + starred_next["items"]]
        assert len(starred_ids) == len(set(starred_ids)) == 27
        filtered = client.get(
            "/api/v1/public/markets", params={"q": "journey 01", "sort": "stars"}
        ).json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["title"] == "Public journey 01"


def test_public_blueprint_and_fork_use_reviewed_snapshot() -> None:
    import asyncio

    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("snapshot-visitor")
    _register(visitor)
    goal = _goal("Get a signed offer")
    goal.success_definition = {
        "event": "signed_offer",
        "milestones": ["Prepare portfolio"],
        "private_journal": "Never publish this",
    }
    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/v1/social/markets/{goal.goal_id}/visibility",
                json={"visibility": "public"},
            ).status_code
            == 200
        )
        reviewed_deadline = goal.deadline
        goal.success_definition["event"] = "changed_after_publication"
        goal.success_definition["private_journal"] = "New secret"
        goal.deadline = reviewed_deadline + timedelta(days=30)
        preview = client.get(f"/api/v1/social/markets/{goal.goal_id}").json()
        assert preview["public_preview"]["success_criteria"]["event"] == "signed_offer"
        app.state.auth_bypass_principal = visitor
        detail = client.get(f"/api/v1/public/markets/{goal.goal_id}").json()
        assert detail["blueprint"]["success_criteria"]["event"] == "signed_offer"
        assert detail["blueprint"]["deadline"] == reviewed_deadline.isoformat().replace(
            "+00:00", "Z"
        )
        assert detail["blueprint"]["milestones"] == ["Prepare portfolio"]
        assert "private_journal" not in str(detail)
        forked = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/fork",
            json={"idempotency_key": "reviewed-snapshot-fork"},
        ).json()
        assert forked["visibility"] == "private"
        copied = client.get(f"/api/v1/goals/{forked['goal_id']}").json()
        assert copied["success_definition"]["event"] == "signed_offer"
        assert copied["deadline"] == reviewed_deadline.isoformat().replace("+00:00", "Z")
        assert "private_journal" not in str(copied)
        app.state.auth_bypass_principal = owner
        assert client.get(f"/api/v1/goals/{forked['goal_id']}").status_code == 404
