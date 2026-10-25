from datetime import UTC, datetime, timedelta
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
from personal_markets.what_if.repository import PostgresSimulationRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_concurrent_same_fingerprint_does_not_double_count() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    goal_id = uuid4()
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('evidence_events')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
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
        observed = datetime.now(UTC).isoformat()
        event = EvidenceEventProposal(
            event_type="manual_state_entry",
            domain="user_state",
            metric="applications",
            numeric_value=11,
            unit="count",
            observed_at=observed,
            source_type="manual",
            summary="Applications submitted so far",
        )

        first = await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=goal_id,
            events=[event],
            agent_run_id=None,
            conflicts=[],
        )
        second = await evidence.commit(
            user_id=DEFAULT_USER_ID,
            goal_id=goal_id,
            events=[event],
            agent_run_id=None,
            conflicts=[],
        )
        rows = await evidence.list_for_goal(goal_id)
        ids = {
            item.evidence_id
            for item in rows
            if item.metric in {"applications", "applications_submitted"}
        }
        assert len(ids) == 1
        assert first.events[0].evidence_id == second.events[0].evidence_id
        outcome = await reprice.publish_if_priceable(goal_id)
        assert outcome.status in {"completed", "limited"}
        markets = PostgresSimulationRepository(engine)
        published = await markets.history(goal_id)
        assert len(published) == 1
        retry = await reprice.publish_if_priceable(goal_id)
        assert retry.status == "unchanged"
        assert len(await markets.history(goal_id)) == 1
    finally:
        await engine.dispose()
