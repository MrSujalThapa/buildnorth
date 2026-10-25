# ruff: noqa: E501,ASYNC240
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import POSTGRES_MIGRATION_SKIP, isolated_postgres_url
from personal_markets.core.config import DEFAULT_USER_ID
from personal_markets.evidence.domain import EvidenceCommit
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
        migration = (
            Path(__file__).resolve().parents[3]
            / "supabase"
            / "migrations"
            / "0024_evidence_fingerprint_unique.sql"
        )
        sql = (
            migration.read_text(encoding="utf-8")
            .replace("begin;", "")
            .replace("commit;", "")
        )
        cleaned = "\n".join(
            line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")
        )
        statements = [part.strip() for part in cleaned.split(";") if part.strip()]
        async with engine.begin() as conn:
            for statement in statements:
                await conn.exec_driver_sql(statement)
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

        async def commit_once() -> EvidenceCommit:
            return await evidence.commit(
                user_id=DEFAULT_USER_ID,
                goal_id=goal_id,
                events=[event],
                agent_run_id=None,
                conflicts=[],
            )

        first, second = await asyncio.gather(commit_once(), commit_once())
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
        async with engine.begin() as conn:
            index = await conn.scalar(
                text(
                    "select indexname from pg_indexes "
                    "where indexname = 'evidence_events_user_fingerprint_live_idx'"
                )
            )
            assert index == "evidence_events_user_fingerprint_live_idx"
            other_user = uuid4()
            await conn.execute(
                text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                {"id": other_user, "clerk": f"test-other-{other_user}"},
            )
        other_goal = GoalContract(
            goal_id=uuid4(),
            title="Receive an SWE offer by 2027",
            goal_type=GoalType.DEADLINE_EVENT,
            success_definition={"metric": "offer_received", "target": "swe_offer"},
            deadline=datetime.now(UTC) + timedelta(days=400),
            state_dimensions=["applications"],
        )
        await goals.create_goal(other_goal, other_user)
        isolated = await evidence.commit(
            user_id=other_user,
            goal_id=other_goal.goal_id,
            events=[event],
            agent_run_id=None,
            conflicts=[],
        )
        owner_rows = await evidence.list_for_goal(goal_id)
        other_rows = await evidence.list_for_goal(other_goal.goal_id)
        assert isolated.events[0].evidence_id != first.events[0].evidence_id
        assert {item.evidence_id for item in owner_rows} != {item.evidence_id for item in other_rows}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fingerprint_migration_keeps_duplicate_rows_as_superseded() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    owner = DEFAULT_USER_ID
    keep_id = uuid4()
    drop_id = uuid4()
    goal_id = uuid4()
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('evidence_events')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            await conn.execute(text("drop index if exists evidence_events_user_fingerprint_idx"))
            await conn.execute(
                text("drop index if exists evidence_events_user_fingerprint_live_idx")
            )
        goals = GoalService(PostgresGoalRepository(engine))
        await goals.create_goal(
            GoalContract(
                goal_id=goal_id,
                title="Keep historical duplicate evidence",
                goal_type=GoalType.DEADLINE_EVENT,
                success_definition={"metric": "offer_received", "target": "swe_offer"},
                deadline=datetime.now(UTC) + timedelta(days=400),
                state_dimensions=["applications"],
            ),
            owner,
        )
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    insert into evidence_events (
                      id, user_id, event_type, domain, metric, numeric_value, unit,
                      observed_at, source_quality, provenance_json, created_at
                    ) values
                    (:keep, :uid, 'manual_state_entry', 'user_state', 'applications', 4, 'count',
                     now(), 'user_confirmed',
                     jsonb_build_object('fingerprint', CAST(:fp AS text)), now() - interval '2 hours'),
                    (:drop, :uid, 'manual_state_entry', 'user_state', 'applications', 4, 'count',
                     now(), 'user_confirmed',
                     jsonb_build_object('fingerprint', CAST(:fp AS text)), now())
                    """
                ),
                {"keep": keep_id, "drop": drop_id, "uid": owner, "fp": f"hist-dup-{keep_id}"},
            )
            await conn.execute(
                text(
                    "insert into goal_evidence (goal_id, evidence_id) values (:gid, :keep), (:gid, :drop) "
                    "on conflict do nothing"
                ),
                {"gid": goal_id, "keep": keep_id, "drop": drop_id},
            )
        migration = (
            Path(__file__).resolve().parents[3]
            / "supabase"
            / "migrations"
            / "0024_evidence_fingerprint_unique.sql"
        )
        sql = (
            migration.read_text(encoding="utf-8")
            .replace("begin;", "")
            .replace("commit;", "")
        )
        cleaned = "\n".join(
            line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")
        )
        statements = [part.strip() for part in cleaned.split(";") if part.strip()]
        async with engine.begin() as conn:
            for statement in statements:
                await conn.exec_driver_sql(statement)
            remaining = (
                await conn.execute(
                    text(
                        "select id, supersedes_id from evidence_events "
                        "where id = :keep or id = :drop"
                    ),
                    {"keep": keep_id, "drop": drop_id},
                )
            ).mappings().all()
        ids = {row["id"]: row["supersedes_id"] for row in remaining}
        assert keep_id in ids and drop_id in ids
        assert ids[keep_id] is None
        assert ids[drop_id] == keep_id
    finally:
        await engine.dispose()
