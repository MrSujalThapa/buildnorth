from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository
from personal_markets.persistence.agent_store import InMemoryAgentRunStore, InMemoryEvidenceRepository
from personal_markets.wiring import get_integration_gateway, get_integration_repository


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
        gateway=get_integration_gateway(),
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

    asyncio.run(repository.create(goal, uuid4()))
    with TestClient(app) as client:
        response = client.get(f"/api/v1/goals/{goal.goal_id}/evidence/sources/plan")
    assert response.status_code == 200
    body = response.json()
    assert "recommended" in body
    assert "irrelevant" in body
