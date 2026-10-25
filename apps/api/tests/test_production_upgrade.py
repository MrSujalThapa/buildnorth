from typing import Any

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.config import Settings
from personal_markets.identity.inference_router import hosted_provider
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_catalog import classify_discovered, hosted_allowlist
from personal_markets.integrations.inference_discovery import parse_provider_models
from personal_markets.integrations.mcp_service import IntegrationGatewayService


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_profile_patch_cors_preflight() -> None:
    with TestClient(isolated_app()) as client:
        response = client.options(
            "/api/v1/profile",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_blank_spur_key_is_treated_as_missing() -> None:
    settings = _settings(spur_api_key="")
    assert settings.spur_api_key is None


def test_auto_hosted_never_falls_back_to_openai() -> None:
    settings = _settings(
        inference_provider="auto", openai_api_key="sk-openai", anthropic_api_key="sk-ant"
    )
    assert hosted_provider(settings) == "none"
    with_spur = settings.model_copy(update={"spur_api_key": "sk-spur"})
    assert hosted_provider(with_spur) == "spur"


def test_hosted_allowlist_is_platform_model_only() -> None:
    assert hosted_allowlist("spur", "spur-glm-5-3") == {"spur-glm-5-3"}


def test_discovered_openai_family_is_structured_without_inventing_ids() -> None:
    payload = {
        "data": [
            {"id": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol"},
            {"id": "whisper-1"},
            {"id": "gpt-5.4-mini"},
        ]
    }
    models = parse_provider_models("openai", payload)
    by_id = {item["model"]: item for item in models}
    assert "gpt-6.1-sol" in by_id
    assert by_id["gpt-6.1-sol"]["structured"] is True
    assert by_id["whisper-1"]["structured"] is False
    assert by_id["gpt-5.4-mini"]["source"] == "catalog"


def test_unverified_anthropic_id_is_not_forecast_compatible() -> None:
    cap = classify_discovered("anthropic", "not-a-claude-model")
    assert cap.structured is False
    assert cap.compatibility == "unverified"


def test_non_admin_me_omits_global_hosted_budget() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        client.app.state.auth_bypass_principal = make_principal("judge-one", invited=True)
        hosted = client.get("/api/v1/me").json()["hosted"]
        assert hosted["global_remaining_usd"] is None
        assert "hosted_available" in hosted
        client.app.state.auth_bypass_principal = make_principal(
            "admin-one", invited=True, role="admin", email="admin@example.com"
        ).model_copy(update={"trusted_admin": True})
        admin = client.get("/api/v1/me").json()["hosted"]
        assert admin["global_remaining_usd"] is not None


def test_plugins_catalog_excludes_builtin_evidence_tools_when_composio_is_off() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/plugins")
        assert response.status_code == 200, response.text
        body = response.json()
        ids = {item["definition"]["id"] for item in body["items"]}
        assert not {"manual", "csv"} & ids
        assert body["provider_status"] in {"unavailable", "available", "error"}


def test_connected_plugin_view_does_not_require_remote_catalog() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/plugins/connected")
        assert response.status_code == 200, response.text
        assert response.json() == []


def test_goals_dashboard_returns_histories_in_one_payload() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        listed = client.get("/api/v1/goals")
        assert listed.status_code == 200, listed.text
        dashboard = client.get("/api/v1/goals/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        body = dashboard.json()
        assert "goals" in body and "histories" in body
        assert isinstance(body["histories"], dict)
        assert "collections" in body


def test_dashboard_batches_owner_scoped_creation_status() -> None:
    import asyncio
    from uuid import uuid4

    from personal_markets.ports import WorkflowSnapshot

    app = isolated_app()
    principal = app.state.auth_bypass_principal
    goal = _sample_goal()
    asyncio.run(app.state.goal_repository.create(goal, principal.user_id))
    threads = app.state.agent_workflow._threads
    foreign = WorkflowSnapshot(
        thread_id=uuid4(), kind="create_goal", status="withheld", current_step="complete",
        goal=goal, debug={"user_id": str(uuid4())},
    )
    asyncio.run(threads.upsert(foreign))
    with TestClient(app) as client:
        assert client.get("/api/v1/goals/dashboard").json()["creation_states"] == {}
        own = foreign.model_copy(update={
            "thread_id": uuid4(), "status": "evidence_pending",
            "debug": {"user_id": str(principal.user_id)},
        })
        asyncio.run(threads.upsert(own))
        response = client.get("/api/v1/goals/dashboard")
        assert response.status_code == 200, response.text
        assert response.json()["creation_states"] == {
            str(goal.goal_id): {"status": "evidence_pending", "critic_decision": None},
        }


def _sample_goal(title: str = "Read twenty books this year", current: int | None = 4):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from personal_markets.goals.domain import GoalContract, GoalType

    definition: dict[str, object] = {"metric": "books", "target": 20}
    if current is not None:
        definition["current"] = current
    return GoalContract(
        goal_id=uuid4(),
        title=title,
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition=definition,
        deadline=datetime.now(UTC) + timedelta(days=200),
        state_dimensions=["reading"],
    )


def test_owner_can_archive_and_restore_goal() -> None:
    import asyncio

    from personal_markets.identity.testing import make_principal

    app = isolated_app()
    principal = app.state.auth_bypass_principal
    goal = _sample_goal()
    asyncio.run(app.state.goal_repository.create(goal, principal.user_id))
    with TestClient(app) as client:
        listed = client.get("/api/v1/goals").json()
        assert any(item["goal_id"] == str(goal.goal_id) for item in listed)
        deleted = client.delete(f"/api/v1/goals/{goal.goal_id}")
        assert deleted.status_code == 200, deleted.text
        assert client.get("/api/v1/goals").json() == []
        assert client.get(f"/api/v1/goals/{goal.goal_id}").status_code == 404
        restored = client.post(f"/api/v1/goals/{goal.goal_id}/restore")
        assert restored.status_code == 200, restored.text
        assert client.get(f"/api/v1/goals/{goal.goal_id}").status_code == 200
        other = make_principal("other-judge", invited=True)
        client.app.state.auth_bypass_principal = other
        denied = client.delete(f"/api/v1/goals/{goal.goal_id}")
        assert denied.status_code in {403, 404}


def test_collections_group_goals_and_report_progress_not_probability() -> None:
    import asyncio

    app = isolated_app()
    principal = app.state.auth_bypass_principal
    goal = _sample_goal()
    asyncio.run(app.state.goal_repository.create(goal, principal.user_id))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/collections", json={"name": "Learning", "goal_ids": [str(goal.goal_id)]}
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["progress"]["label"] == "progress"
        assert body["progress"]["value"] == 0.2
        dashboard = client.get("/api/v1/goals/dashboard").json()
        assert dashboard["collections"][0]["collection"]["name"] == "Learning"


def test_collection_excludes_withheld_member_from_current_odds() -> None:
    import asyncio
    from uuid import UUID, uuid4

    from personal_markets.collections.service import CollectionService
    from personal_markets.goals.service import GoalService
    from personal_markets.ports import WorkflowSnapshot

    app = isolated_app()
    principal = app.state.auth_bypass_principal
    goal = _sample_goal()
    asyncio.run(app.state.goal_repository.create(goal, principal.user_id))
    snapshot = WorkflowSnapshot(
        thread_id=uuid4(), kind="create_goal", status="withheld", current_step="complete",
        goal=goal, debug={"user_id": str(principal.user_id)},
    )
    asyncio.run(app.state.agent_workflow._threads.upsert(snapshot))
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/collections", json={"name": "Reading", "goal_ids": [str(goal.goal_id)]}
        )
        assert created.status_code == 200, created.text
        assert created.json()["portfolio_odds"] is None
        assert created.json()["priced_goals"] == 0
        row = asyncio.run(app.state.collection_repository.get_for_user(
            UUID(created.json()["collection"]["collection_id"]), principal.user_id,
        ))
        assert row is not None
        service = CollectionService(
            app.state.collection_repository, GoalService(app.state.goal_repository)
        )
        history = {str(goal.goal_id): [{"probability": 0.15, "created_at": "2026-10-20T12:00:00Z"}]}
        view = asyncio.run(service.view(row, [goal], history, {goal.goal_id}))
        assert len(view.series[0].points) == 1
        assert view.portfolio_odds is None
        assert view.priced_goals == 0


def test_profile_username_is_unique_and_private() -> None:
    from personal_markets.identity.testing import make_principal

    app = isolated_app()
    with TestClient(app) as client:
        patched = client.patch(
            "/api/v1/profile", json={"username": "judge_one", "display_name": "Judge"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["profile"]["username"] == "judge_one"
        profile = client.get("/api/v1/profile").json()
        assert profile["privacy"] == "private"
        assert all(
            value is None
            for series in profile["traits"]["series"]
            for value in series["values"].values()
        )
        assert len(profile["selected_parameters"]) >= 3
        assert profile["radar"]["parameters"]
        assert all(item["value"] is None for item in profile["radar"]["parameters"])
        selected = ["reading_minutes", "monthly_savings", "weekly_running_km"]
        changed = client.patch("/api/v1/profile", json={"parameter_ids": selected})
        assert changed.status_code == 200, changed.text
        persisted = client.get("/api/v1/profile").json()
        assert persisted["selected_parameters"] == selected
        assert [item["id"] for item in persisted["radar"]["parameters"]] == selected
        demo = client.get("/api/v1/profile/demo-radar")
        assert demo.status_code == 200
        assert demo.json()["synthetic"] is True
        assert demo.json()["fixture_goal_count"] == 0
        assert demo.json()["commitment_count"] == 0
        client.app.state.auth_bypass_principal = make_principal("second-judge", invited=True)
        taken = client.patch("/api/v1/profile", json={"username": "judge_one"})
        assert taken.status_code == 409


def test_withhold_snapshot_is_classified() -> None:
    from personal_markets.goals.publication import classify_withhold, publication_snapshot
    from personal_markets.ports import CriticArtifact

    critic = CriticArtifact(decision="withhold", issues=["Missing current reading progress"])
    assert classify_withhold(critic) == "missing_user_information"
    snap = publication_snapshot(critic, "withheld")
    assert snap["status"] == "withheld"
    assert snap["required_actions"]


def test_async_agent_start_returns_then_reaches_interrupt() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/threads",
            json={
                "kind": "create_goal",
                "intent": (
                    "I want to receive an SWE/FDE offer from one of my "
                    "target companies by August 2027."
                ),
            },
            headers={"Prefer": "respond-async"},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["thread_id"]
        assert body["status"] in {
            "running",
            "needs_input",
            "completed",
            "limited",
            "withheld",
        }
        polled = client.get(f"/api/v1/agent/threads/{body['thread_id']}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["status"] in {
            "running",
            "needs_input",
            "completed",
            "limited",
            "withheld",
            "failed",
        }
        if polled.json()["status"] == "running":
            assert created.json()["status"] == "running"


async def test_plugin_search_does_not_advertise_builtin_evidence_as_integrations() -> None:
    from uuid import uuid4

    service = IntegrationGatewayService()
    catalog = await service.search_catalog(search="csv", user_id=uuid4())
    ids = {item["definition"]["id"] for item in catalog["items"]}
    assert "csv" not in ids
