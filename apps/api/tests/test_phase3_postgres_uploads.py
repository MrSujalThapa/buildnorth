import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import isolated_postgres_url
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.evidence.uploads import PostgresUploadStore, UploadService
from personal_markets.persistence.database import create_engine

pytestmark = pytest.mark.integration
_MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def _apply_upload_migrations(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as connection:
        exists = connection.execute("select to_regclass('goal_uploads')").fetchone()[0]
        if exists is None:
            connection.execute((_MIGRATIONS / "0013_goal_uploads.sql").read_text(encoding="utf-8"))
        connection.execute((_MIGRATIONS / "0014_goal_upload_blobs.sql").read_text(encoding="utf-8"))


async def _seed_owner_goal(engine, owner_id, goal_id) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "insert into app_users (id, clerk_user_id) "
                "values (:id, :clerk) on conflict do nothing"
            ),
            {"id": owner_id, "clerk": f"clerk-{owner_id}"},
        )
        await connection.execute(
            text("""
            insert into goals (
              id, user_id, title, goal_type, success_definition_json, deadline
            ) values (
              :id, :user_id, 'Upload persistence', 'threshold',
              '{"metric":"subscribers","operator":">=","target":"10"}'::jsonb,
              :deadline
            ) on conflict (id) do nothing
            """),
            {
                "id": goal_id,
                "user_id": owner_id,
                "deadline": datetime.now(UTC) + timedelta(days=30),
            },
        )


@pytest.mark.asyncio
async def test_postgres_uploads_survive_new_store_and_isolate_tenants() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    _apply_upload_migrations(url)
    engine = create_engine(url)
    engine_b = None
    owner = uuid4()
    other = uuid4()
    goal = uuid4()
    other_goal = uuid4()
    raw = b"date,subscribers\n2026-01-01,800\n2026-02-01,900\n"
    try:
        await _seed_owner_goal(engine, owner, goal)
        await _seed_owner_goal(engine, other, other_goal)
        store = PostgresUploadStore(engine)
        first = UploadService(store)
        record = await first.ingest(owner, goal, "subs.csv", raw, "text/csv")
        duplicate = await first.ingest(owner, goal, "subs.csv", raw, "text/csv")
        assert duplicate.upload_id == record.upload_id
        engine_b = create_engine(url)
        restarted_store = PostgresUploadStore(engine_b)
        restarted = UploadService(restarted_store)
        loaded = await restarted.get(owner, record.upload_id)
        assert loaded.sha256 == record.sha256
        assert loaded.filename == "subs.csv"
        blob = await restarted_store.load_blob(owner, loaded)
        assert blob == raw
        with pytest.raises(ResourceNotFoundError):
            await restarted.get(other, record.upload_id)
        assert await restarted.list_for_goal(other, goal) == []
        await restarted.delete(owner, record.upload_id)
        with pytest.raises(ResourceNotFoundError):
            await restarted.get(owner, record.upload_id)
        restored = await restarted.ingest(owner, goal, "subs.csv", raw, "text/csv")
        assert restored.upload_id != record.upload_id
    finally:
        await engine.dispose()
        if engine_b is not None:
            await engine_b.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_uploads_dedupe() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    _apply_upload_migrations(url)
    engine = create_engine(url)
    owner = uuid4()
    goal = uuid4()
    raw = b"week,value\n2026-01-07,1\n"
    try:
        await _seed_owner_goal(engine, owner, goal)
        service = UploadService(PostgresUploadStore(engine))
        rows = await asyncio.gather(
            *[service.ingest(owner, goal, "a.csv", raw, "text/csv") for _ in range(6)]
        )
        assert len({item.upload_id for item in rows}) == 1
        listed = await service.list_for_goal(owner, goal)
        assert len(listed) == 1
    finally:
        await engine.dispose()
