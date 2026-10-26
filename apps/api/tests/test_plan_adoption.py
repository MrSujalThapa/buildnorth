"""Adopted What If plans: stored as hypotheses, re-evaluated, never counted as evidence."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.behavior.commitments import (
    Commitment,
    InMemoryCommitmentStore,
    OutcomeStatus,
    get_commitment_store,
    trials_from_commitments,
)
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.what_if.domain import InterventionChangeInput
from personal_markets.what_if.service import WhatIfService
from test_change_end_to_end import _hiring_goal, _seed_evidence

PLAN_CHANGE = InterventionChangeInput(
    metric="weekly_application_rate",
    operation="add",
    value=5,
    unit="applications/week",
    frequency="week",
    provenance="USER_ASSUMPTION",
)


def _plan_body(start: datetime) -> dict[str, object]:
    return {
        "domain": "career",
        "action": "Send applications",
        "planned_quantity": 40,
        "unit": "applications",
        "window_start": start.isoformat(),
        "window_end": (start + timedelta(weeks=8)).isoformat(),
        "plan_context": {
            "title": "What if I send 5 more applications a week",
            "family": "applications",
            "option_id": "direct",
            "changes": [PLAN_CHANGE.model_dump(exclude={"scope", "provenance"})],
            "quantity_per_period": 5,
            "period": "week",
            "duration_periods": 8,
            "baseline_probability": 0.31,
            "scenario_probability": 0.4,
            "execution_probability": 0.72,
            "assumptions_used": ["+5 applications/week until the deadline."],
            "priced_at": start.isoformat(),
        },
    }


def test_adopted_plan_keeps_its_scenario_and_is_not_a_trial_until_observed() -> None:
    get_commitment_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal = _hiring_goal()
    asyncio.run(app.state.agent_workflow._inner._deps.goals._repository.create(goal, owner))
    start = datetime.now(UTC)
    path = f"/api/v1/goals/{goal.goal_id}/commitments"
    with TestClient(app) as client:
        created = client.post(path, json=_plan_body(start))
        assert created.status_code == 200, created.text
        context = created.json()["plan_context"]
        assert context["scenario_probability"] == 0.4
        assert context["changes"][0]["metric"] == "weekly_application_rate"
        listed = client.get(path).json()
        assert listed["commitments"][0]["plan_context"]["title"].startswith("What if")
        assert trials_from_commitments(
            [Commitment.model_validate(item) for item in listed["commitments"]], []
        ) == []
        bad = _plan_body(start)
        bad["plan_context"] = {**bad["plan_context"], "scenario_probability": 1.4}  # type: ignore[dict-item]
        assert client.post(path, json=bad).status_code == 422
        smuggled = _plan_body(start)
        smuggled["plan_context"] = {**smuggled["plan_context"], "observed": True}  # type: ignore[dict-item]
        assert client.post(path, json=smuggled).status_code == 422

        abandoned = client.post(
            f"{path}/{created.json()['id']}/observations",
            json={"status": "cancelled", "observed_at": start.isoformat()},
        )
        assert abandoned.status_code == 200
        evaluated = client.post(
            "/api/v1/what-if/plan-evaluation",
            json={"goal_id": str(goal.goal_id), "changes": [PLAN_CHANGE.model_dump()]},
        )
        assert evaluated.status_code == 200


async def _service_for(owner: UUID, goal: GoalContract, outcomes: list[float]) -> WhatIfService:
    goals = InMemoryGoalRepository()
    await goals.create(goal, owner)
    evidence = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed_evidence(
        evidence,
        goal.goal_id,
        owner,
        [
            ("career", "applications_submitted", 15, "count"),
            ("career", "phone_screens_completed", 3, "count"),
        ],
    )
    store = get_commitment_store()
    assert isinstance(store, InMemoryCommitmentStore)
    end = datetime.now(UTC) - timedelta(days=1)
    for index, fraction in enumerate(outcomes):
        window_end = end - timedelta(weeks=index)
        plan = await store.create(
            Commitment(
                owner_id=owner,
                goal_id=goal.goal_id,
                domain="career",
                action="Send applications",
                planned_quantity=10,
                unit="applications",
                window_start=window_end - timedelta(weeks=1),
                window_end=window_end,
            )
        )
        status: OutcomeStatus = (
            "completed" if fraction >= 1 else "missed" if fraction <= 0 else "partial"
        )
        quantity = 10 if fraction >= 1 else 0 if fraction <= 0 else 10 * fraction
        await store.observe(
            owner, plan.id, status=status, actual_quantity=quantity, observed_at=window_end
        )
    return WhatIfService(GoalService(goals), evidence=EvidenceService(evidence), owner_id=owner)


@pytest.mark.asyncio
async def test_two_users_with_different_follow_through_get_different_plan_odds() -> None:
    get_commitment_store.cache_clear()
    reliable_goal = _hiring_goal()
    flaky_goal = reliable_goal.model_copy(update={"goal_id": uuid4()})
    reliable = await _service_for(uuid4(), reliable_goal, [1, 1, 1, 1, 1, 1, 1, 0.8])
    flaky = await _service_for(uuid4(), flaky_goal, [0, 0, 0.2, 0, 0, 0.3, 0, 0])

    high = await reliable.evaluate_plan(str(reliable_goal.goal_id), [PLAN_CHANGE])
    low = await flaky.evaluate_plan(str(flaky_goal.goal_id), [PLAN_CHANGE])
    assert high.priced and low.priced
    assert high.execution_probability is not None and low.execution_probability is not None
    assert high.execution_probability > low.execution_probability
    assert high.baseline_probability == pytest.approx(low.baseline_probability)
    assert (high.scenario_probability or 0) - (high.baseline_probability or 0) > (
        (low.scenario_probability or 0) - (low.baseline_probability or 0)
    )
    assert (high.execution_breakdown or {}).get("source") != "USER_ASSUMPTION"
