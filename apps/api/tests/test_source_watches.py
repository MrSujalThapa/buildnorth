from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.integrations.goal_sync_jobs import InMemoryGoalSyncJobStore
from personal_markets.integrations.source_watches import InMemorySourceWatchStore, SourceWatch


@pytest.mark.asyncio
async def test_watch_requires_owner_and_goal_to_change_status() -> None:
    store = InMemorySourceWatchStore()
    watch = await store.save(
        SourceWatch(
            owner_id=uuid4(),
            goal_id=uuid4(),
            plugin_connection_id=uuid4(),
            plugin_id="notion",
            resource_id="approved-resource",
        )
    )
    assert await store.set_status(uuid4(), watch.goal_id, watch.id, "paused") is None
    assert await store.set_status(watch.owner_id, uuid4(), watch.id, "paused") is None
    assert (await store.list_for_goal(watch.owner_id, watch.goal_id))[0].status == "active"
    assert await store.active_resource_uris(watch.owner_id, watch.goal_id) == {
        "composio://notion/approved-resource"
    }
    paused = await store.set_status(watch.owner_id, watch.goal_id, watch.id, "paused")
    assert paused is not None and paused.status == "paused"
    assert await store.active_resource_uris(watch.owner_id, watch.goal_id) == set()


@pytest.mark.asyncio
async def test_due_watch_enqueues_once_and_respects_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemorySourceWatchStore()
    jobs = InMemoryGoalSyncJobStore()
    monkeypatch.setattr(
        "personal_markets.integrations.source_watches.get_goal_sync_job_store", lambda: jobs
    )
    watch = await store.save(
        SourceWatch(
            owner_id=uuid4(),
            goal_id=uuid4(),
            plugin_connection_id=uuid4(),
            plugin_id="notion",
            resource_id="approved-resource",
            next_check_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    assert await store.enqueue_due() == 1
    assert await store.enqueue_due() == 0
    assert (await jobs.latest(watch.owner_id, watch.goal_id)) is not None
    await store.set_status(watch.owner_id, watch.goal_id, watch.id, "paused")
    assert await store.enqueue_due() == 0


@pytest.mark.asyncio
async def test_due_watch_waits_for_existing_job(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemorySourceWatchStore()
    jobs = InMemoryGoalSyncJobStore()
    monkeypatch.setattr(
        "personal_markets.integrations.source_watches.get_goal_sync_job_store", lambda: jobs
    )
    watch = await store.save(
        SourceWatch(
            owner_id=uuid4(), goal_id=uuid4(), plugin_connection_id=uuid4(),
            plugin_id="notion", resource_id="approved-resource",
            next_check_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    manual = await jobs.enqueue(watch.owner_id, watch.goal_id)
    assert await store.enqueue_due() == 0
    assert (await store.list_for_goal(watch.owner_id, watch.goal_id))[0].next_check_at <= datetime.now(UTC)
    await jobs.update(manual.id, status="completed")
    assert await store.enqueue_due() == 1
