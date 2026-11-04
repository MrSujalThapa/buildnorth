"""A persisted goal-to-forecast-to-chart-to-scenario journey."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import POSTGRES_MIGRATION_SKIP, isolated_postgres_url
from personal_markets.core.config import DEFAULT_USER_ID
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import PostgresBaselineForecastRepository
from personal_markets.forecasting.reprice import BaselineRepriceService
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import PostgresEvidenceRepository
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.remote_mcp.charting import series_from_history
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.repository import PostgresSimulationRepository
from personal_markets.what_if.service import WhatIfService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_persisted_user_journey_and_unrelated_goal() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('market_forecast_history')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
        goals = GoalService(PostgresGoalRepository(engine))
        evidence = EvidenceService(PostgresEvidenceRepository(engine))
        forecasts = BaselineForecastService(PostgresBaselineForecastRepository(engine))
        reprice = BaselineRepriceService(goals, evidence, forecasts)
        scenarios = WhatIfService(
            goals,
            PostgresSimulationRepository(engine),
            evidence=evidence,
            owner_id=DEFAULT_USER_ID,
            forecasts=forecasts,
        )

        async def make_goal(
            title: str, kind: GoalType, metric: str, target: object
        ) -> GoalContract:
            goal = GoalContract(
                goal_id=uuid4(),
                title=title,
                goal_type=kind,
                success_definition=(
                    {"metric": metric, "target": target}
                    if kind == GoalType.DEADLINE_EVENT
                    else {"metric": metric, "operator": ">=", "amount": target}
                ),
                deadline=datetime.now(UTC) + timedelta(days=360),
                state_dimensions=["applications"]
                if kind == GoalType.DEADLINE_EVENT
                else ["net_worth"],
            )
            await goals.create_goal(goal, DEFAULT_USER_ID)
            return goal

        async def record(
            goal: GoalContract, metric: str, value: float, unit: str,
            kind: Literal["snapshot", "increment"],
        ) -> None:
            await evidence.commit(
                user_id=DEFAULT_USER_ID,
                goal_id=goal.goal_id,
                events=[
                    EvidenceEventProposal(
                        event_type="observation",
                        domain="career" if metric == "applications" else "finance",
                        metric=metric,
                        numeric_value=value,
                        unit=unit,
                        observed_at=datetime.now(UTC).isoformat(),
                        source_type="manual",
                        observation_kind=kind,
                        summary=f"{metric}: {value}",
                    )
                ],
                agent_run_id=None,
                conflicts=[],
            )

        goal = await make_goal(
            "Receive a software engineering offer",
            GoalType.DEADLINE_EVENT,
            "offer_received",
            "swe_offer",
        )
        await record(goal, "applications", 18, "count", "snapshot")
        first = await reprice.publish_if_priceable(goal.goal_id)
        assert first.status in {"completed", "limited"}
        await record(goal, "applications", 5, "count", "increment")
        second = await reprice.publish_if_priceable(goal.goal_id)
        assert second.status in {"completed", "limited"}
        history = await forecasts.published_history(goal.goal_id)
        assert len(history) == 2
        chart = series_from_history(history)
        assert len(chart) == 2
        assert [point["probability"] for point in chart] == pytest.approx(
            [item.probability for item in history]
        )
        state = await scenarios.baseline_state(str(goal.goal_id))
        assert state.priced and state.current_probability is not None
        assert state.published_relation == "same_inputs", (
            state.evaluation_input_hash,
            history[-1].receipt.get("evaluation_input_hash"),
            state.current_probability,
            history[-1].probability,
        )
        assert state.current_probability == pytest.approx(history[-1].probability)
        request = WhatIfRequest(
            goal_id=str(goal.goal_id),
            current_value=state.current_value or 0,
            target_value=state.target_value or 1,
            periods=state.periods or 1,
            assumptions=state.assumptions,
            parsed_changes=[
                InterventionChangeInput(
                    metric="applications_per_week",
                    operation="set",
                    value=10,
                    unit="count/week",
                    provenance="user_stated",
                )
            ],
        )
        result = await scenarios.simulate(request)
        assert result.priced and result.persisted
        assert result.baseline_probability is not None
        assert result.baseline_probability == pytest.approx(history[-1].probability)
        assert result.scenario_probability is not None
        assert result.conditional_on_execution_probability is not None
        assert result.execution_probability is not None
        assert (
            result.baseline_probability
            <= result.scenario_probability
            <= result.conditional_on_execution_probability
        )
        retry = await reprice.publish_if_priceable(goal.goal_id)
        assert retry.status == "unchanged"
        assert retry.probability == history[-1].probability
        assert len(await forecasts.published_history(goal.goal_id)) == 2

        unrelated = await make_goal("Practice piano each day", GoalType.HABIT, "piano_session", 30)
        await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=unrelated.goal_id,
            events=[
                EvidenceEventProposal(
                    event_type="completed",
                    domain="music",
                    metric="piano_session",
                    categorical_value="completed",
                    observed_at=datetime.now(UTC).isoformat(),
                    source_type="manual",
                    summary="Completed today's piano practice",
                )
            ],
            agent_run_id=None,
            conflicts=[],
        )
        other = await reprice.publish_if_priceable(unrelated.goal_id)
        assert other.status in {"completed", "limited"}, other.reason
        other_history = await forecasts.published_history(unrelated.goal_id)
        assert len(other_history) == 1
        assert len(series_from_history(other_history)) == 1
        other_state = await scenarios.baseline_state(str(unrelated.goal_id))
        assert other_state.published_probability == pytest.approx(other_history[-1].probability)
        assert not other_state.priced  # Habit scenario simulation is not implemented.
    finally:
        await engine.dispose()
