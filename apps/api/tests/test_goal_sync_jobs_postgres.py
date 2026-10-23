from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import POSTGRES_MIGRATION_SKIP, isolated_postgres_url
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.integrations.goal_sync_jobs import PostgresGoalSyncJobStore
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_goal_sync_job_claim_dedupe_and_owner_scope() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    engine = create_engine(url)
    owner, other, goal_id = uuid4(), uuid4(), uuid4()
    migrated = False
    try:
        async with engine.begin() as connection:
            if not await connection.scalar(text("select to_regclass('goal_sync_jobs')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            migrated = True
            await connection.execute(
                text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                {"id": owner, "clerk": f"sync-test-{owner}"},
            )
        goal = GoalContract(
            goal_id=goal_id,
            title="Sync test goal",
            goal_type=GoalType.CONTINUOUS_TARGET,
            success_definition={"metric": "books_read", "target": 20},
            deadline=datetime.now(UTC) + timedelta(days=30),
            state_dimensions=["books_read"],
        )
        await PostgresGoalRepository(engine).create(goal, owner)
        store = PostgresGoalSyncJobStore(engine)
        first = await store.enqueue(owner, goal_id)
        assert (await store.enqueue(owner, goal_id)).id == first.id
        assert await store.get(other, goal_id, first.id) is None
        claimed = await store.claim()
        assert claimed and claimed.id == first.id and claimed.status == "fetching_sources"
        await store.update(
            first.id,
            status="completed",
            receipt={"records_added": 1},
            finished_at=datetime.now(UTC),
        )
        assert (await store.get(owner, goal_id, first.id)).receipt["records_added"] == 1
        second = await store.enqueue(owner, goal_id)
        assert second.id != first.id
        assert (await store.latest(owner, goal_id)).id == second.id
        await store.update(second.id, receipt={"origin": "watch"})
        assert await store.claim() is None
        watched = await store.claim(include_watches=True)
        assert watched is not None and watched.id == second.id
    finally:
        if migrated:
            async with engine.begin() as connection:
                await connection.execute(
                    text("delete from goal_sync_jobs where owner_id = :owner"), {"owner": owner}
                )
                await connection.execute(
                    text("delete from goals where id = :goal"), {"goal": goal_id}
                )
                await connection.execute(
                    text("delete from app_users where id = :owner"), {"owner": owner}
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_raw_source_identifiers_are_scoped_to_owner() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    engine = create_engine(url)
    first_owner, second_owner = uuid4(), uuid4()
    first_event, second_event = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            if not await connection.scalar(
                text("select to_regclass('raw_source_events_owner_external_idx')")
            ):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            for owner, event in ((first_owner, first_event), (second_owner, second_event)):
                await connection.execute(
                    text("""
                    insert into raw_source_events
                      (id, user_id, source_type, external_event_id, content_fingerprint,
                       observed_at, raw_payload_ref)
                    values (:event, :owner, 'notion', 'shared-provider-id',
                            'shared-content-hash', now(), 'test://shared')
                    """),
                    {"event": event, "owner": owner},
                )
            assert (
                await connection.scalar(
                    text("""
                select count(*) from raw_source_events
                where id in (:first_event, :second_event)
            """),
                    {"first_event": first_event, "second_event": second_event},
                )
                == 2
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("delete from raw_source_events where id in (:first, :second)"),
                {"first": first_event, "second": second_event},
            )
        await engine.dispose()
