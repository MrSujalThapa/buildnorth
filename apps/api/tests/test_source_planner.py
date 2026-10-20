from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.agents.source_planner_service import (
    SourcePlannerService,
    _arguments_for_resource,
    _select_capabilities,
)
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.goal_sync_service import _supported_goal_step
from personal_markets.integrations.mcp_domain import ReadCapabilityRecord
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
)
from personal_markets.ports import SourcePlannerProposal, SourceRecommendation
from personal_markets.wiring import get_integration_repository, integration_gateway_for


def test_github_recipe_selects_only_requested_read_actions() -> None:
    connection_id = uuid4()
    names = ["GITHUB_LIST_COMMITS", "GITHUB_GET_PULL_REQUESTS", "GITHUB_GET_A_REPOSITORY"]
    capabilities = [
        ReadCapabilityRecord(
            id=uuid4(),
            plugin_connection_id=connection_id,
            capability_id=name.lower(),
            label=name,
            operation="read",
            tool_name=name,
            approved=True,
        )
        for name in names
    ]
    selected = _select_capabilities(capabilities, ["commits", "pull_requests"])
    assert [item.tool_name for item in selected] == names[:2]
    assert _select_capabilities(capabilities, ["reviews"]) == []


def test_notion_recipe_reads_the_selected_page() -> None:
    connection_id = uuid4()
    capabilities = [
        ReadCapabilityRecord(
            id=uuid4(),
            plugin_connection_id=connection_id,
            capability_id=name.lower(),
            label=name,
            operation="read",
            tool_name=name,
            approved=True,
            input_schema={"properties": {"block_id": {"type": "string"}}},
        )
        for name in ("NOTION_FETCH_ALL_BLOCK_CONTENTS", "NOTION_SEARCH_NOTION_PAGE")
    ]
    selected = _select_capabilities(capabilities, None)
    assert [item.tool_name for item in selected] == ["NOTION_FETCH_ALL_BLOCK_CONTENTS"]
    assert (
        _arguments_for_resource("page-123", "Book Reports", selected[0])["block_id"] == "page-123"
    )


def test_legacy_search_recipe_cannot_be_mistaken_for_notion_content() -> None:
    assert not _supported_goal_step("notion", "NOTION_SEARCH_NOTION_PAGE")
    assert _supported_goal_step("notion", "NOTION_FETCH_ALL_BLOCK_CONTENTS")
    assert not _supported_goal_step("github", "GITHUB_GET_A_REPOSITORY")
    assert _supported_goal_step("github", "GITHUB_LIST_COMMITS")


def test_accessible_book_report_promotes_notion_for_reading_goal() -> None:
    proposal = SourcePlannerProposal(
        goal_title="Read 20 books",
        goal_type="continuous_target",
        state_dimensions=["books_read"],
        irrelevant=[
            SourceRecommendation(plugin_id="notion", relevance="irrelevant", rationale="No match")
        ],
    )
    result = SourcePlannerService._attach_ranked_resources(
        proposal,
        [
            {
                "plugin_id": "notion",
                "resource_id": "page-1",
                "label": "Oct 20th book report",
                "resource_type": "page",
            }
        ],
        {"title": "Read 20 books by end of 2026", "state_dimensions": ["books_read"]},
    )
    assert [item.plugin_id for item in result.recommended] == ["notion"]
    assert result.recommended[0].resources[0].recommended


@pytest.mark.asyncio
async def test_source_planner_recommends_goal_specific_sources() -> None:
    get_integration_repository.cache_clear()
    goal = GoalContract(
        goal_id=uuid4(),
        title="Break 45 minutes in a 10K",
        goal_type=GoalType.THRESHOLD,
        success_definition={"metric": "10k_time_seconds", "target": 2700},
        deadline=datetime.now(UTC) + timedelta(days=120),
        state_dimensions=["weekly_distance_km", "training_consistency"],
    )
    repo = InMemoryGoalRepository()
    await repo.create(goal, uuid4())
    service = SourcePlannerService(
        settings=Settings(environment="test"),
        inference=ScriptedInferenceProvider(),
        goals=GoalService(repo),
        evidence=EvidenceService(InMemoryEvidenceRepository()),
        gateway=integration_gateway_for(uuid4()),
        run_store=InMemoryAgentRunStore(),
        repository=get_integration_repository(),
    )
    plan = await service.plan(str(goal.goal_id))
    recommended_ids = {item.plugin_id for item in plan.recommended}
    irrelevant_ids = {item.plugin_id for item in plan.irrelevant}
    assert "strava" in recommended_ids or "notion" in recommended_ids
    assert "github" in irrelevant_ids or not recommended_ids.intersection({"github"})


def test_source_plan_api() -> None:
    get_integration_repository.cache_clear()
    app = isolated_app()
    goal = GoalContract(
        goal_id=uuid4(),
        title="Receive an FDE internship offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received", "target": "fde_offer"},
        deadline=datetime.now(UTC) + timedelta(days=120),
        state_dimensions=["interview_outcomes", "applications_submitted"],
    )
    repository = app.state.agent_workflow._inner._deps.goals._repository
    import asyncio

    asyncio.run(repository.create(goal, app.state.auth_bypass_principal.user_id))
    with TestClient(app) as client:
        response = client.get(f"/api/v1/goals/{goal.goal_id}/evidence/sources/plan")
        arbitrary_step = client.post(
            f"/api/v1/goals/{goal.goal_id}/evidence/sources/github/recipe",
            json={
                "label": "repo",
                "resource_ids": ["owner/repo"],
                "steps": [{"capability_id": "write", "tool_name": "GITHUB_DELETE_REPOSITORY"}],
            },
        )
    assert response.status_code == 200
    assert arbitrary_step.status_code == 422
    body = response.json()
    assert "recommended" in body
    assert "irrelevant" in body
