from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import isolated_postgres_url
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
from personal_markets.what_if.repository import PostgresSimulationRepository

pytestmark = pytest.mark.integration


def _test_database_url() -> str | None:
    return isolated_postgres_url()


@pytest.mark.asyncio
async def test_phase0_publish_survives_repository_reload() -> None:
    url = _test_database_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    goal_id = uuid4()
    try:
        goals = GoalService(PostgresGoalRepository(engine))
        evidence = EvidenceService(PostgresEvidenceRepository(engine))
        forecasts = BaselineForecastService(PostgresBaselineForecastRepository(engine))
        reprice = BaselineRepriceService(goals, evidence, forecasts)
        goal = GoalContract(
            goal_id=goal_id,
            title="Receive an SWE offer by 2027",
            goal_type=GoalType.DEADLINE_EVENT,
            success_definition={"metric": "offer_received", "target": "swe_offer"},
            deadline=datetime.now(UTC) + timedelta(days=400),
            state_dimensions=["applications"],
        )
        await goals.create_goal(goal, DEFAULT_USER_ID)
        await evidence.watch_goal(goal_id)
        first = await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=goal_id,
            events=[
                EvidenceEventProposal(
                    event_type="manual_state_entry",
                    domain="user_state",
                    metric="applications",
                    numeric_value=6,
                    unit="count",
                    observed_at=datetime.now(UTC).isoformat(),
                    source_type="manual",
                    summary="Applications submitted so far",
                )
            ],
            agent_run_id=None,
            conflicts=[],
        )
        assert first.events
        outcome = await reprice.publish_if_priceable(goal_id)
        assert outcome.status in {"completed", "limited"}
        assert outcome.probability is not None
        first_probability = outcome.probability

        duplicate = await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=goal_id,
            events=[
                EvidenceEventProposal(
                    event_type="manual_state_entry",
                    domain="user_state",
                    metric="applications",
                    numeric_value=6,
                    unit="count",
                    observed_at=first.events[0].observed_at.isoformat()
                    if first.events[0].observed_at
                    else datetime.now(UTC).isoformat(),
                    source_type="manual",
                    summary="Applications submitted so far",
                )
            ],
            agent_run_id=None,
            conflicts=[],
        )
        assert duplicate.events[0].evidence_id == first.events[0].evidence_id
        unchanged = await reprice.publish_if_priceable(goal_id)
        assert unchanged.status == "unchanged"

        second = await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=goal_id,
            events=[
                EvidenceEventProposal(
                    event_type="manual_state_entry",
                    domain="user_state",
                    metric="applications",
                    numeric_value=18,
                    unit="count",
                    observed_at=datetime.now(UTC).isoformat(),
                    source_type="manual",
                    summary="Updated application count",
                )
            ],
            agent_run_id=None,
            conflicts=[],
        )
        assert second.events[0].evidence_id != first.events[0].evidence_id
        updated = await reprice.publish_if_priceable(goal_id)
        assert updated.status in {"completed", "limited"}
        assert updated.probability is not None
        assert updated.probability != first_probability

        fresh = PostgresBaselineForecastRepository(engine)
        history = await fresh.load_history(goal_id)
        assert len(history) == 2
        assert all(point.source_kind == "published_forecast" for point in history)
        assert history[-1].receipt.get("llm_used_for_probability") is False
        assert history[-1].receipt.get("final_probability") is not None

        markets = PostgresSimulationRepository(engine)
        api_history = await markets.history(goal_id)
        published = [point for point in api_history if point.source_kind == "published_forecast"]
        assert [point.probability for point in published] == [
            point.probability for point in history
        ]

        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "select count(*) from market_forecast_history "
                        "where goal_id=:id and source_kind='published_forecast'"
                    ),
                    {"id": goal_id},
                )
            ).scalar_one()
        assert int(row) == 2
    finally:
        await engine.dispose()
