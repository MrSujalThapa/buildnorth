from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.reprice import BaselineRepriceService
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType, ResourceConstraints
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal


def _finance_goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        version=1,
        title="Build a $20,000 emergency fund by December 2027",
        goal_type=GoalType.THRESHOLD,
        success_definition={
            "metric": "emergency_fund_balance",
            "target": 20000,
            "unit": "USD",
            "operator": ">=",
        },
        deadline=datetime(2027, 12, 31, tzinfo=UTC),
        state_dimensions=["current_balance", "monthly_contribution"],
        resource_constraints=ResourceConstraints(hours_per_week=5),
        model_requirements={"compatibility": "exploratory_finance"},
    )


@pytest.mark.asyncio
async def test_manual_state_reprice_publishes_when_priceable() -> None:
    goals_repo = InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository()
    goal = _finance_goal()
    user_id = uuid4()
    await goals_repo.create(goal, user_id)
    evidence = EvidenceService(evidence_repo)
    await evidence.commit(
        user_id=user_id,
        goal_id=goal.goal_id,
        events=[
            EvidenceEventProposal(
                event_type="manual_state_entry",
                domain="user_state",
                metric="current_balance",
                numeric_value=4200,
                unit="USD",
                observed_at="2026-08-30T00:00:00Z",
                source_type="manual",
                summary="Current balance entered by the user",
            ),
            EvidenceEventProposal(
                event_type="manual_state_entry",
                domain="user_state",
                metric="monthly_contribution",
                numeric_value=600,
                unit="USD/month",
                observed_at="2026-08-30T00:00:00Z",
                source_type="manual",
                summary="Monthly contribution entered by the user",
            ),
        ],
        agent_run_id=None,
        conflicts=[],
    )
    forecasts = BaselineForecastService(InMemoryBaselineForecastRepository())
    service = BaselineRepriceService(GoalService(goals_repo), evidence, forecasts)
    status = await service.publish_if_priceable(goal.goal_id)
    assert status.status in {"completed", "limited"}
    history = forecasts.history(goal.goal_id)
    assert history
    assert history[-1].probability > 0

    second = await service.publish_if_priceable(goal.goal_id)
    assert second.status == "unchanged"
