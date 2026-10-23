from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from personal_markets.integrations.goal_sync_jobs import InMemoryGoalSyncJobStore
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.integrations.mcp_domain import GoalSyncRecipeRecord, SyncRecipeStep
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
async def test_watch_result_tracks_failure_and_last_success_without_cross_owner_write() -> None:
    store = InMemorySourceWatchStore()
    watch = await store.save(SourceWatch(
        owner_id=uuid4(), goal_id=uuid4(), plugin_connection_id=uuid4(),
        plugin_id="github", resource_id="owner/repo",
    ))
    uri = "composio://github/owner/repo"
    await store.record_result(uuid4(), watch.goal_id, [uri], error="Permission denied")
    assert (await store.list_for_goal(watch.owner_id, watch.goal_id))[0].last_error is None
    await store.record_result(watch.owner_id, watch.goal_id, [uri], error="Permission denied")
    failed = (await store.list_for_goal(watch.owner_id, watch.goal_id))[0]
    assert failed.last_error == "Permission denied"
    assert failed.last_success_at is None
    await store.record_result(watch.owner_id, watch.goal_id, [uri], error=None)
    succeeded = (await store.list_for_goal(watch.owner_id, watch.goal_id))[0]
    assert succeeded.last_error is None
    assert succeeded.last_success_at is not None


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


@pytest.mark.asyncio
async def test_due_watch_job_reads_only_due_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemorySourceWatchStore()
    jobs = InMemoryGoalSyncJobStore()
    monkeypatch.setattr(
        "personal_markets.integrations.source_watches.get_goal_sync_job_store", lambda: jobs
    )
    owner_id, goal_id, connection_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    for resource_id, due_at in (
        ("page-a", now - timedelta(minutes=1)),
        ("page-b", now - timedelta(minutes=1)),
        ("page-later", now + timedelta(minutes=30)),
    ):
        await store.save(SourceWatch(
            owner_id=owner_id, goal_id=goal_id, plugin_connection_id=connection_id,
            plugin_id="notion", resource_id=resource_id, next_check_at=due_at,
        ))

    assert await store.enqueue_due() == 2
    job = await jobs.latest(owner_id, goal_id)
    assert job is not None
    assert job.receipt["watch_resource_uris"] == [
        "composio://notion/page-a", "composio://notion/page-b",
    ]
    later = next(
        w for w in await store.list_for_goal(owner_id, goal_id)
        if w.resource_id == "page-later"
    )
    assert later.last_checked_at is None
    assert later.next_check_at > now


@pytest.mark.asyncio
async def test_parent_watch_reads_only_discovered_children_and_rechecks_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySourceWatchStore()
    monkeypatch.setattr(
        "personal_markets.integrations.goal_sync_service.get_source_watch_store",
        lambda: store,
    )
    owner_id, goal_id, connection_id = uuid4(), uuid4(), uuid4()
    parent_id, child_id = str(uuid4()), str(uuid4())
    watch = await store.save(SourceWatch(
        owner_id=owner_id, goal_id=goal_id, plugin_connection_id=connection_id,
        plugin_id="notion", resource_id=parent_id, scope="parent",
    ))
    recipe = GoalSyncRecipeRecord(
        goal_id=goal_id, plugin_connection_id=connection_id, plugin_id="notion",
        label="Book Reports", approved=True, steps=[SyncRecipeStep(
            capability_id="read-page", tool_name="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            resource_uri=f"composio://notion/{parent_id}",
            arguments={"block_id": parent_id},
        )],
    )
    gateway = SimpleNamespace(
        list_descendants=AsyncMock(return_value=[child_id]),
        sync=AsyncMock(return_value={"records_read": 0, "new_records": []}),
    )
    service = GoalSyncService(
        settings=None, gateway=gateway,
        repository=SimpleNamespace(list_goal_recipes=AsyncMock(return_value=[recipe])),
        goals=SimpleNamespace(get_goal_by_string=AsyncMock(return_value=SimpleNamespace(goal_id=goal_id))),
        workflow=None, evidence=None, owner_id=owner_id,
        watch_resource_uris=[f"composio://notion/{parent_id}"],
    )
    assert (await service.sync_goal_sources(str(goal_id)))["status"] == "no_new_records"
    steps = gateway.sync.await_args.kwargs["steps"]
    assert [step.resource_uri for step in steps] == [
        f"composio://notion/{parent_id}", f"composio://notion/{child_id}",
    ]
    await store.set_status(owner_id, goal_id, watch.id, "revoked")
    gateway.sync.reset_mock()
    assert (await service.sync_goal_sources(str(goal_id)))["status"] == "no_recipes"
    gateway.sync.assert_not_awaited()
