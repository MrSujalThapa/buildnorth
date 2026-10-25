from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.agents.intervention_critic import critique_intervention
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
)
from personal_markets.ports import InterventionAgentProposal, InterventionStateChange


def career_goal() -> GoalContract:
    goal_id = uuid4()
    return GoalContract(
        goal_id=goal_id,
        title="Receive an SWE/FDE offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received", "target": "swe_or_fde_offer"},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=["interview_outcomes", "practice_volume", "applications_submitted"],
    )


@pytest.mark.asyncio
async def test_intervention_agent_maps_linkedin_semantically() -> None:
    goal = career_goal()
    repo = InMemoryGoalRepository()
    await repo.create(goal, uuid4())
    service = InterventionAgentService(
        settings=Settings(
            environment="test",
            intervention_agent_enabled=True,
            intervention_regex_fallback=False,
        ),
        inference=ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(repo),
        evidence=EvidenceService(InMemoryEvidenceRepository()),
        run_store=InMemoryAgentRunStore(),
    )
    parsed = await service.parse(
        str(goal.goal_id), "What if I start posting on LinkedIn 4 times a week?"
    )
    assert parsed.pricing_status in {"PRICED", "ASSUMPTION_REQUIRED"}
    assert parsed.changes
    assert parsed.changes[0].metric == "linkedin_posts_per_week"
    assert parsed.effect_assigned is False or parsed.pricing_status == "ASSUMPTION_REQUIRED"
    assert all("probability" not in item.metric for item in parsed.changes)
    assert parsed.mechanism


def test_intervention_critic_rejects_probability_fields() -> None:
    goal = career_goal()
    proposal = InterventionAgentProposal(
        understood_action="Boost odds",
        mechanism=[],
        changes=[
            InterventionStateChange(
                metric="weekly_application_rate",
                operation="add",
                value=0.08,
                unit="probability",
                provenance="EXPLORATION_ASSUMPTION",
                strength="EXPLORATORY",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(goal, proposal)
    assert critic.approved is False
    assert critic.pricing_status == "NOT_PRICED"


def test_cold_email_cannot_become_unmeasured_application_uplift() -> None:
    proposal = InterventionAgentProposal(
        understood_action="Send 10 cold emails",
        changes=[
            InterventionStateChange(
                metric="weekly_application_rate",
                operation="add",
                value=10,
                unit="count/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(career_goal(), proposal, "What if I send 10 cold emails?")
    assert not critic.approved
    assert not critic.validated_changes
    assert "not measured applications" in critic.issues[0]


@pytest.mark.parametrize(
    "text,value,operation",
    [
        ("What if I submit 5 additional applications each week?", 5, "add"),
        ("what if i send 5 more applications every week", 5, "add"),
        ("what if i apply to 20 jobs next week", 20, "set"),
        ("what if i do 10 applications a week", 10, "set"),
        (
            "What if I increase applications from 8 per week to 15 per week "
            "for the next two months?",
            15,
            "set",
        ),
        ("What if I increase from 8/week by 7/week?", 7, "add"),
        ("What if I do 15 applications/week instead of 8?", 15, "set"),
    ],
)
def test_explicit_weekly_application_changes_survive_critique(
    text: str, value: float, operation: Literal["set", "add", "subtract"]
) -> None:
    proposal = InterventionAgentProposal(
        understood_action=text,
        changes=[
            InterventionStateChange(
                metric="applications_per_week",
                operation=operation,
                value=value,
                unit="applications/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(career_goal(), proposal, text)
    assert critic.approved
    assert critic.validated_changes[0].value == value
    assert critic.validated_changes[0].operation == operation


@pytest.mark.parametrize(
    "text,value,operation",
    [
        ("What if I send 10 cold emails and 5 applications?", 5, "add"),
        ("What if I study 5 hours and apply to jobs?", 5, "set"),
        ("What if I send 5 more applications each week?", 5, "set"),
        ("What if I submit 5 applications each week?", 5, "add"),
        ("What if I apply to 20 jobs next week?", 15, "set"),
        ("I completed 15 applications yesterday", 15, "set"),
        ("What if I send 15 additional applications?", 15, "add"),
    ],
)
def test_application_critic_rejects_unstated_or_wrong_semantics(
    text: str, value: float, operation: Literal["set", "add", "subtract"]
) -> None:
    proposal = InterventionAgentProposal(
        understood_action=text,
        changes=[
            InterventionStateChange(
                metric="applications_per_week",
                operation=operation,
                value=value,
                unit="applications/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    assert not critique_intervention(career_goal(), proposal, text).approved


def test_study_hours_cannot_invent_a_daily_practice_quantity() -> None:
    proposal = InterventionAgentProposal(
        understood_action="Study for 10 hours tomorrow",
        changes=[
            InterventionStateChange(
                metric="daily_practice_problems",
                operation="set",
                value=20,
                unit="count/day",
                provenance="USER_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(career_goal(), proposal, "What if I study 10 hours tomorrow?")
    assert not critic.approved
    assert not critic.validated_changes


def _composed_career_goal() -> GoalContract:
    goal = career_goal()
    return goal.model_copy(
        update={
            "model_requirements": {
                "forecast_spec": {
                    "family": "composed_growth",
                    "primitives": [
                        {
                            "id": "primary",
                            "kind": "growth",
                            "config": {"time_unit": "week"},
                            "unit": "count",
                        }
                    ],
                }
            }
        }
    )


def test_composed_career_spec_still_accepts_application_rate() -> None:
    proposal = InterventionAgentProposal(
        understood_action="Increase applications to 15 per week",
        changes=[
            InterventionStateChange(
                metric="applications_per_week",
                operation="set",
                value=15,
                unit="applications/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(
        _composed_career_goal(),
        proposal,
        "What if I increase my applications from 8 per week to 15 per week "
        "for the next two months?",
    )
    assert critic.approved
    assert critic.validated_changes[0].value == 15
    assert critic.validated_changes[0].operation == "set"


def test_composed_career_spec_rejects_unmodeled_mock_interviews() -> None:
    proposal = InterventionAgentProposal(
        understood_action="Four mock interviews",
        changes=[
            InterventionStateChange(
                metric="mock_interviews_per_week",
                operation="set",
                value=4,
                unit="count/week",
                provenance="EXPLORATION_ASSUMPTION",
            )
        ],
        pricing_status="PRICED",
    )
    critic = critique_intervention(
        _composed_career_goal(),
        proposal,
        "What if I do four mock interviews per week?",
    )
    assert not critic.approved
    assert not critic.validated_changes


def test_parse_intervention_api_uses_agent() -> None:
    app = isolated_app()
    goal = career_goal()
    repository = app.state.agent_workflow._inner._deps.goals._repository
    import asyncio

    asyncio.run(repository.create(goal, app.state.auth_bypass_principal.user_id))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/what-if/parse-intervention",
            json={
                "goal_id": str(goal.goal_id),
                "text": "What if I do 3 mock interviews per week?",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["changes"]
    assert body["changes"][0]["metric"] == "mock_interviews_per_week"
    assert body["effect_assigned"] is False
