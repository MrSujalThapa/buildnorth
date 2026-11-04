from datetime import UTC, datetime, timedelta
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
from personal_markets.what_if.domain import WhatIfRequest
from personal_markets.what_if.service import WhatIfService


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

    await evidence.commit(
        user_id, goal.goal_id,
        [EvidenceEventProposal(
            event_type="observation", domain="daily_life", metric="unrelated_activity",
            numeric_value=1, unit="count", observed_at=datetime.now(UTC).isoformat(),
            source_type="manual", summary="Opened a tool during lunch",
        )], None, [],
    )
    informational = await service.publish_if_priceable(goal.goal_id)
    assert informational.probability is not None
    assert informational.receipt is not None
    assert informational.receipt["controlled_evidence_comparison"]["status"] == "informational"


@pytest.mark.asyncio
async def test_real_goal_publication_and_unchanged_what_if_use_same_evidence() -> None:
    goals_repo = InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository()
    goal = _finance_goal()
    user_id = uuid4()
    await goals_repo.create(goal, user_id)
    evidence = EvidenceService(evidence_repo)
    await evidence.commit(
        user_id, goal.goal_id,
        [
            EvidenceEventProposal(
                event_type="manual_state_entry", domain="user_state", metric="current_balance",
                numeric_value=4200, unit="USD", observed_at="2026-08-30T00:00:00Z",
                source_type="manual", summary="Real balance",
            ),
            EvidenceEventProposal(
                event_type="manual_state_entry", domain="user_state",
                metric="monthly_contribution", numeric_value=600, unit="USD/month",
                observed_at="2026-08-30T00:00:00Z", source_type="manual",
                summary="Real contribution",
            ),
            EvidenceEventProposal(
                event_type="manual_state_entry", domain="user_state", metric="current_balance",
                numeric_value=999999, unit="USD", observed_at="2026-08-31T00:00:00Z",
                source_type="manual", summary="Seed balance", event_identity="seed:fixture",
            ),
        ], None, [],
    )
    forecasts = BaselineForecastService(InMemoryBaselineForecastRepository())
    goals = GoalService(goals_repo)
    published = await BaselineRepriceService(goals, evidence, forecasts).publish_if_priceable(
        goal.goal_id
    )
    assert published.probability is not None
    baseline = await WhatIfService(goals, evidence=evidence, forecasts=forecasts).baseline_state(
        str(goal.goal_id)
    )
    assert baseline.current_probability == pytest.approx(published.probability)
    assert baseline.published_probability == pytest.approx(published.probability)
    assert baseline.published_relation == "same_inputs"


@pytest.mark.asyncio
async def test_hiring_publication_and_unchanged_what_if_share_evaluation_inputs() -> None:
    goal = GoalContract(
        goal_id=uuid4(), version=1, title="Get an FDE offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received", "target": "fde_offer"},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=["applications_submitted", "interview_outcomes"],
    )
    goals_repo = InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository()
    user_id = uuid4()
    await goals_repo.create(goal, user_id)
    evidence = EvidenceService(evidence_repo)
    await evidence.commit(
        user_id, goal.goal_id,
        [EvidenceEventProposal(
            event_type="observation", domain="hiring", metric="applications_submitted",
            numeric_value=20, unit="count", observed_at=datetime.now(UTC).isoformat(),
            source_type="manual", summary="Twenty applications sent",
        )], None, [],
    )
    forecasts = BaselineForecastService(InMemoryBaselineForecastRepository())
    published = await BaselineRepriceService(
        GoalService(goals_repo), evidence, forecasts
    ).publish_if_priceable(goal.goal_id)
    assert published.probability is not None
    evaluated_at = datetime.fromisoformat(
        forecasts.history(goal.goal_id)[-1].receipt["evaluated_at"]
    )
    baseline = await WhatIfService(
        GoalService(goals_repo), evidence=evidence, forecasts=forecasts
    ).baseline_state(str(goal.goal_id), now=evaluated_at)
    assert baseline.published_relation == "same_inputs"
    assert baseline.current_probability == pytest.approx(published.probability)
    assert baseline.current_value is not None
    assert baseline.target_value is not None
    assert baseline.periods is not None
    unchanged = await WhatIfService(
        GoalService(goals_repo), evidence=evidence, forecasts=forecasts
    ).fast_reprice(WhatIfRequest(
        goal_id=str(goal.goal_id), current_value=baseline.current_value,
        target_value=baseline.target_value, periods=baseline.periods,
        direction=baseline.direction, assumptions=baseline.assumptions,
        config=baseline.config,
    ))
    assert unchanged.priced
    assert unchanged.baseline_probability == pytest.approx(
        unchanged.scenario_probability
    )
