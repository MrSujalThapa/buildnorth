from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.baseline_state import build_baseline_state
from personal_markets.what_if.domain import WhatIfRequest
from personal_markets.what_if.intervention_parser import parse_intervention_text
from personal_markets.what_if.request_intent import classify_what_if_request
from personal_markets.what_if.service import WhatIfService


def _hiring_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Receive a Big Tech SWE offer",
            "goal_type": GoalType.DEADLINE_EVENT,
            "success_definition": {"metric": "offer_received", "target": "swe_offer"},
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "state_dimensions": ["application_pipeline", "interview_outcomes"],
            "resource_constraints": {"hours_per_week": 20},
        }
    )


def _habit_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Complete 12 guitar practice sessions",
            "goal_type": GoalType.THRESHOLD,
            "success_definition": {"metric": "practice_sessions", "operator": ">=", "value": 12},
            "deadline": datetime.now(UTC) + timedelta(days=90),
            "state_dimensions": ["practice_sessions"],
        }
    )


@pytest.mark.asyncio
async def test_hypothetical_application_rate_does_not_write_evidence() -> None:
    assert (
        classify_what_if_request("What if I apply to 10 jobs a week?").kind
        == "quantitative_scenario"
    )
    goal = _hiring_goal()
    user_id = uuid4()
    goals = InMemoryGoalRepository()
    await goals.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    evidence = EvidenceService(evidence_repo)
    before = await evidence.list_for_goal(goal.goal_id)
    parsed = parse_intervention_text("What if I apply to 10 jobs a week?")
    service = WhatIfService(GoalService(goals), evidence=evidence)
    baseline = build_baseline_state(goal, before)
    if baseline.priced and parsed.changes:
        await service.simulate(
            WhatIfRequest.model_validate(
                {
                    "goal_id": str(goal.goal_id),
                    "current_value": baseline.current_value or 0,
                    "target_value": baseline.target_value or 1,
                    "periods": baseline.periods or 1,
                    "direction": baseline.direction,
                    "assumptions": baseline.assumptions,
                    "parsed_changes": [asdict(item) for item in parsed.changes],
                    "intervention": baseline.default_intervention,
                    "config": baseline.config,
                }
            )
        )
    after = await evidence.list_for_goal(goal.goal_id)
    assert after == before


@pytest.mark.asyncio
async def test_confirmed_application_evidence_is_idempotent() -> None:
    goal = _hiring_goal()
    user_id = uuid4()
    goals = InMemoryGoalRepository()
    await goals.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    service = EvidenceService(evidence_repo)
    event = EvidenceEventProposal.model_validate(
        {
            "source_type": "manual",
            "event_type": "observation",
            "domain": "career",
            "metric": "applications_submitted",
            "numeric_value": 10,
            "unit": "count",
            "observed_at": datetime.now(UTC).isoformat(),
            "summary": "Submitted 10 applications this week",
            "observation_kind": "period",
        }
    )
    first = await service.commit(user_id, goal.goal_id, [event], None, [])
    second = await service.commit(user_id, goal.goal_id, [event], None, [])
    rows = await service.list_for_goal(goal.goal_id)
    assert len(first.events) == 1
    assert len(rows) == 1
    assert second.events[0].evidence_id == first.events[0].evidence_id


@pytest.mark.asyncio
async def test_founder_introductions_are_not_application_counts() -> None:
    classified = classify_what_if_request("I got introduced to 3 founders")
    assert classified.kind == "evidence_report"
    goal = _hiring_goal()
    user_id = uuid4()
    goals = InMemoryGoalRepository()
    await goals.create(goal, user_id)
    service = EvidenceService(InMemoryEvidenceRepository({goal.goal_id: True}))
    event = EvidenceEventProposal.model_validate(
        {
            "source_type": "manual",
            "event_type": "observation",
            "domain": "career",
            "metric": "manual_note",
            "categorical_value": "Introduced to three founders",
            "observed_at": datetime.now(UTC).isoformat(),
            "summary": "Introduced to three founders",
        }
    )
    await service.commit(user_id, goal.goal_id, [event], None, [])
    rows = await service.list_for_goal(goal.goal_id)
    assert rows[0].metric != "applications_submitted"
    assert rows[0].numeric_value is None


@pytest.mark.asyncio
async def test_habit_session_evidence_does_not_double_count() -> None:
    goal = _habit_goal()
    user_id = uuid4()
    goals = InMemoryGoalRepository()
    await goals.create(goal, user_id)
    repo = InMemoryEvidenceRepository({goal.goal_id: True})
    service = EvidenceService(repo)
    event = EvidenceEventProposal.model_validate(
        {
            "source_type": "manual",
            "event_type": "observation",
            "domain": "personal",
            "metric": "practice_sessions",
            "numeric_value": 2,
            "unit": "count",
            "observed_at": datetime.now(UTC).isoformat(),
            "summary": "Finished two sessions yesterday",
            "observation_kind": "increment",
        }
    )
    await service.commit(user_id, goal.goal_id, [event], None, [])
    await service.commit(user_id, goal.goal_id, [event], None, [])
    rows = await service.list_for_goal(goal.goal_id)
    assert len(rows) == 1
    assert rows[0].numeric_value == 2
