# ruff: noqa: E501
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.core.config import Settings
from personal_markets.core.errors import TransientProviderError
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import (
    FailingInferenceProvider,
    ScriptedInferenceProvider,
    default_agent_script,
)
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
)
from personal_markets.ports import EvidenceEventProposal, InferenceProvider, InferenceRequest


def _career_goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Receive an SWE/FDE offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received", "target": "swe_or_fde_offer"},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=["interview_outcomes", "practice_volume", "applications_submitted"],
    )


async def _service(
    goal: GoalContract,
    *,
    inference: InferenceProvider | None = None,
    evidence_summaries: list[str] | None = None,
) -> InterventionAgentService:
    repo = InMemoryGoalRepository()
    user_id = uuid4()
    await repo.create(goal, user_id)
    store = InMemoryEvidenceRepository({goal.goal_id: True})
    evidence = EvidenceService(store)
    for summary in evidence_summaries or []:
        await evidence.commit(
            user_id,
            goal.goal_id,
            [
                EvidenceEventProposal.model_validate(
                    {
                        "source_type": "manual",
                        "event_type": "observation",
                        "domain": "career",
                        "metric": "manual_note",
                        "categorical_value": summary,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "summary": summary,
                    }
                )
            ],
            None,
            [],
        )
    return InterventionAgentService(
        settings=Settings(environment="test", intervention_agent_enabled=True),
        inference=inference or ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(repo),
        evidence=evidence,
        run_store=InMemoryAgentRunStore(),
    )


@pytest.mark.asyncio
async def test_strategy_output_comes_from_the_model_not_a_domain_template() -> None:
    unique = f"ask-the-recorded-lab-mentor-{uuid4().hex[:8]}"

    def script(request: InferenceRequest) -> dict[str, Any]:
        if request.agent_name != "strategy":
            return default_agent_script(request)
        return {
            "understood_question": request.input["question"],
            "insights": [
                {
                    "title": unique,
                    "description": "The model invented this title for this request.",
                    "why_it_might_help": "A named mentor can open a conversation.",
                    "why_this_fits": "Authorized notes mention a lab mentor.",
                    "next_step": "Send a two-sentence ask with the target role.",
                    "evidence_to_collect": "Whether the mentor made an intro.",
                    "constraints": "Uses social capital once.",
                    "model_status": "UNPRICED",
                    "grounded_facts": ["Lab mentor offered to help after the internship."],
                    "assumptions": [],
                    "sources": [],
                }
            ],
            "limitations": [],
            "research_claims": [],
        }

    goal = _career_goal()
    service = await _service(
        goal,
        inference=ScriptedInferenceProvider(script),
        evidence_summaries=["Lab mentor offered to help after the internship."],
    )
    parsed = await service.parse(str(goal.goal_id), "What's my highest-leverage next move?")
    assert parsed.request_kind in {"opportunity_discovery", "strategic_advice"}
    assert parsed.insights
    assert parsed.insights[0].title == unique
    assert parsed.insights[0].model_status == "UNPRICED"
    assert parsed.agent_run_id
    assert all("probability" not in item.title.lower() for item in parsed.insights)


@pytest.mark.asyncio
async def test_same_goal_different_questions_yield_different_recommendations() -> None:
    goal = _career_goal()
    service = await _service(
        goal,
        evidence_summaries=["Submitted 40 applications. Failed two onsite loops."],
    )
    access = await service.parse(str(goal.goal_id), "How do I get access to hiring managers?")
    prep = await service.parse(str(goal.goal_id), "How do I prepare for a technical interview?")
    assert access.insights and prep.insights
    assert access.insights[0].title != prep.insights[0].title
    assert "hiring manager" in access.insights[0].title.lower() or "access" in (
        access.insights[0].description + access.insights[0].title
    ).lower()
    assert "interview" in (prep.insights[0].title + prep.insights[0].description).lower()


@pytest.mark.asyncio
async def test_same_question_different_evidence_yields_different_recommendations() -> None:
    question = "What's my highest-leverage next move?"
    volume = _career_goal()
    interviews = _career_goal()
    volume_service = await _service(
        volume, evidence_summaries=["Submitted 60 applications this quarter. No interviews."]
    )
    interview_service = await _service(
        interviews,
        evidence_summaries=["Had four onsites. Failed system design twice."],
    )
    a = await volume_service.parse(str(volume.goal_id), question)
    b = await interview_service.parse(str(interviews.goal_id), question)
    assert a.insights[0].title != b.insights[0].title


@pytest.mark.asyncio
async def test_current_odds_does_not_attach_strategy_cards() -> None:
    goal = _career_goal()
    parsed = await (await _service(goal)).parse(str(goal.goal_id), "What are my odds right now?")
    assert parsed.request_kind == "current_odds"
    assert parsed.insights == []
    assert "published" in parsed.consumer_summary.lower() or "no published" in parsed.consumer_summary.lower()


@pytest.mark.asyncio
async def test_evidence_report_offers_confirmation_not_strategy_cards() -> None:
    goal = _career_goal()
    parsed = await (await _service(goal)).parse(str(goal.goal_id), "I got two interviews yesterday.")
    assert parsed.request_kind == "evidence_report"
    assert parsed.insights == []
    assert parsed.confirmation_needed is True


@pytest.mark.asyncio
async def test_inference_failure_is_honest_unavailable() -> None:
    goal = _career_goal()
    service = await _service(
        goal, inference=FailingInferenceProvider(TransientProviderError("provider down"))
    )
    parsed = await service.parse(str(goal.goal_id), "What's the smartest move I haven't tried?")
    assert parsed.insights == []
    assert parsed.agent_run_id is None
    assert any("unavailable" in item.lower() for item in parsed.limitations)
    assert "generic" in parsed.consumer_summary.lower() or "unavailable" in parsed.consumer_summary.lower()


def test_parse_intervention_http_returns_model_insights() -> None:
    marker = f"http-insight-{uuid4().hex[:8]}"

    def script(request: InferenceRequest) -> dict[str, Any]:
        if request.agent_name != "strategy":
            return default_agent_script(request)
        return {
            "understood_question": request.input["question"],
            "insights": [
                {
                    "title": marker,
                    "description": "HTTP contract must pass model text through.",
                    "why_it_might_help": "Specific to this question.",
                    "why_this_fits": "No extra private facts.",
                    "next_step": "Ask one person for an intro.",
                    "evidence_to_collect": "Whether the intro happened.",
                    "constraints": "Time this week.",
                    "model_status": "UNPRICED",
                    "grounded_facts": [],
                    "assumptions": ["You may know someone; it is not recorded."],
                    "sources": [],
                }
            ],
            "limitations": [],
            "research_claims": [],
        }

    app = isolated_app(inference=ScriptedInferenceProvider(script))
    goal = _career_goal()
    import asyncio

    asyncio.run(
        app.state.goal_repository.create(goal, app.state.auth_bypass_principal.user_id)
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": str(goal.goal_id), "text": "what's the smartest move I haven't tried yet?"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_kind"] == "opportunity_discovery"
    assert body["insights"][0]["title"] == marker
    assert body["changes"] == []
