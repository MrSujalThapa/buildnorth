import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import ForbiddenError
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.integrations.goal_sync_jobs import (
    InMemoryGoalSyncJobStore,
    get_goal_sync_job_store,
)
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.integrations.goal_sync_worker import (
    execute_goal_sync_job,
    goal_sync_worker,
    public_sync_error,
)
from personal_markets.integrations.mcp_domain import RawSourceRecord
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository


def test_credit_failure_keeps_the_source_tracked_and_unverified() -> None:
    message = public_sync_error(ForbiddenError("this account has no hosted inference entitlement"))
    assert message.startswith("Source tracked — evidence interpretation pending")
    assert "unverified" in message
    assert "Reconnect" not in message


@pytest.mark.asyncio
async def test_sync_jobs_dedupe_and_scope_by_owner() -> None:
    store = InMemoryGoalSyncJobStore()
    owner, other, goal = uuid4(), uuid4(), uuid4()
    first = await store.enqueue(owner, goal)
    repeat = await store.enqueue(owner, goal)
    assert first.id == repeat.id
    assert await store.get(other, goal, first.id) is None
    claimed = await store.claim()
    assert claimed and claimed.id == first.id
    await store.update(first.id, status="completed", finished_at=datetime.now(UTC))
    assert (await store.enqueue(owner, goal)).id != first.id


@pytest.mark.asyncio
async def test_web_worker_cannot_claim_watch_job() -> None:
    store = InMemoryGoalSyncJobStore()
    job = await store.enqueue(uuid4(), uuid4())
    await store.update(job.id, receipt={"origin": "watch"})
    assert await store.claim() is None
    claimed = await store.claim(include_watches=True)
    assert claimed is not None and claimed.id == job.id


@pytest.mark.asyncio
async def test_in_memory_latest_job_uses_insertion_order_when_timestamps_tie() -> None:
    store = InMemoryGoalSyncJobStore()
    owner_id, goal_id = uuid4(), uuid4()
    first = await store.enqueue(owner_id, goal_id)
    await store.update(first.id, status="failed")
    second = await store.enqueue(owner_id, goal_id)
    store._jobs[second.id] = second.model_copy(update={"created_at": first.created_at})
    latest = await store.latest(owner_id, goal_id)
    assert latest is not None and latest.id == second.id
    await store.update(second.id, status="failed")
    third = await store.enqueue(owner_id, goal_id)
    assert third.receipt["replay_job_ids"] == [str(first.id), str(second.id)]


@pytest.mark.asyncio
async def test_stranded_sync_is_reported_without_automatic_retry() -> None:
    store = InMemoryGoalSyncJobStore()
    job = await store.enqueue(uuid4(), uuid4())
    await store.claim()
    await store.update(job.id, started_at=datetime.now(UTC) - timedelta(minutes=5))
    assert await store.expire_stranded() == 1
    assert (await store.get(job.owner_id, job.goal_id, job.id)).status == "timed_out"
    assert await store.claim() is None


@pytest.mark.asyncio
async def test_manual_retry_carries_failed_job_records_with_owner_scope() -> None:
    store = InMemoryGoalSyncJobStore()
    repository = InMemoryIntegrationRepository()
    owner, other, goal_id = uuid4(), uuid4(), uuid4()
    first = await store.enqueue(owner, goal_id)
    record = RawSourceRecord(
        id=uuid4(),
        plugin_connection_id=uuid4(),
        external_id="page-1",
        tool_identity="NOTION_GET_PAGE_MARKDOWN",
        retrieved_at=datetime.now(UTC),
        payload={"content": "Six books finished"},
        payload_hash="hash-1",
        sync_run_id=uuid4(),
        cursor_context={"user_id": str(owner), "goal_sync_job_id": str(first.id)},
    )
    await repository.append_raw_records([record])
    await store.update(first.id, status="failed", finished_at=datetime.now(UTC))
    retry = await store.enqueue(owner, goal_id)
    assert retry.receipt["replay_job_ids"] == [str(first.id)]
    assert await repository.list_job_raw_records(owner, [first.id]) == [record]
    assert await repository.list_job_raw_records(other, [first.id]) == []
    await store.update(retry.id, status="failed", finished_at=datetime.now(UTC))
    next_retry = await store.enqueue(owner, goal_id)
    assert next_retry.receipt["replay_job_ids"] == [str(first.id), str(retry.id)]


@pytest.mark.asyncio
async def test_retry_fetches_providers_missing_from_saved_rows() -> None:
    owner, goal_id, previous_id = uuid4(), uuid4(), uuid4()
    github_row = RawSourceRecord(
        id=uuid4(), plugin_connection_id=uuid4(), external_id="commit-1",
        tool_identity="GITHUB_LIST_COMMITS", retrieved_at=datetime.now(UTC),
        payload={"summary": "Unrelated commit"}, payload_hash="hash-1",
        sync_run_id=uuid4(), cursor_context={"user_id": str(owner), "source_type": "github"},
    )
    calls: list[str] = []

    class Repository:
        async def list_goal_recipes(self, _goal_id):
            return [
                SimpleNamespace(approved=True, plugin_id=provider, steps=[
                    SimpleNamespace(tool_name=tool)
                ])
                for provider, tool in (
                    ("github", "GITHUB_LIST_COMMITS"),
                    ("notion", "NOTION_GET_PAGE_MARKDOWN"),
                )
            ]

        async def list_job_raw_records(self, _owner, _job_ids):
            return [github_row]

    class Gateway:
        async def sync(self, provider, **_kwargs):
            calls.append(provider)
            return {"records_read": 0, "records_new": 0, "new_records": []}

    class Goals:
        async def get_goal_by_string(self, _goal_id, *, owner_id):
            assert owner_id == owner
            return SimpleNamespace(goal_id=goal_id)

    class Workflow:
        async def start(self, request):
            assert len(request.mcp_records) == 1
            return SimpleNamespace(status="unchanged")

    service = GoalSyncService(
        settings=None, gateway=Gateway(), repository=Repository(), goals=Goals(),
        workflow=Workflow(), evidence=None, owner_id=owner,
        replay_job_ids=[previous_id],
    )
    await service.sync_goal_sources(str(goal_id))
    assert calls == ["notion"]


def test_goal_sync_api_acknowledges_job_and_recovers_status() -> None:
    get_goal_sync_job_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal = GoalContract(
        goal_id=uuid4(),
        title="Read 20 books",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "books_read", "target": 20},
        deadline=datetime.now(UTC) + timedelta(days=60),
        state_dimensions=["books_read"],
    )
    asyncio.run(app.state.agent_workflow._inner._deps.goals._repository.create(goal, owner))
    path = f"/api/v1/goals/{goal.goal_id}/evidence/sources/sync"
    with TestClient(app) as client:
        queued = client.post(path)
        assert queued.status_code == 202
        job_id = queued.json()["id"]
        assert client.get(path).json()["id"] == job_id
        assert client.get(f"{path}/{job_id}").status_code == 200
        assert client.get(f"{path}/{uuid4()}").status_code == 404
        assert client.get(path).json()["status"] == "queued"


@pytest.mark.asyncio
async def test_worker_completes_queued_job_without_recipes() -> None:
    get_goal_sync_job_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal = GoalContract(
        goal_id=uuid4(),
        title="Read 20 books",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "books_read", "target": 20},
        deadline=datetime.now(UTC) + timedelta(days=60),
        state_dimensions=["books_read"],
    )
    await app.state.agent_workflow._inner._deps.goals._repository.create(goal, owner)
    store = get_goal_sync_job_store()
    queued = await store.enqueue(owner, goal.goal_id)
    claimed = await store.claim()
    assert claimed and claimed.id == queued.id
    await execute_goal_sync_job(app, claimed)
    completed = await store.get(owner, goal.goal_id, queued.id)
    assert completed and completed.status == "completed"
    assert completed.receipt["status"] == "no_recipes"


@pytest.mark.asyncio
async def test_worker_completes_when_source_has_no_goal_impact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_goal_sync_job_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal_id = uuid4()
    store = get_goal_sync_job_store()
    queued = await store.enqueue(owner, goal_id)
    claimed = await store.claim()
    assert claimed is not None

    async def unchanged(self, goal_id, *, on_stage=None):  # noqa: ANN001
        return SimpleNamespace(
            thread_id=uuid4(), status="unchanged", evidence=[], pricing=None,
        )

    monkeypatch.setattr(GoalSyncService, "sync_goal_sources", unchanged)
    await execute_goal_sync_job(app, claimed)
    completed = await store.get(owner, goal_id, queued.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.receipt["workflow_status"] == "unchanged"


@pytest.mark.asyncio
async def test_worker_records_withheld_forecast_as_successful_source_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_goal_sync_job_store.cache_clear()
    app = isolated_app()
    owner, goal_id = app.state.auth_bypass_principal.user_id, uuid4()
    store = get_goal_sync_job_store()
    queued = await store.enqueue(owner, goal_id)
    claimed = await store.claim()
    assert claimed is not None

    async def withheld(
        self: GoalSyncService, goal_id: str, *, on_stage: object = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            thread_id=uuid4(), status="withheld", evidence=[], pricing=None,
        )

    monkeypatch.setattr(GoalSyncService, "sync_goal_sources", withheld)
    await execute_goal_sync_job(app, claimed)
    completed = await store.get(owner, goal_id, queued.id)
    assert completed is not None and completed.status == "completed"
    assert completed.receipt["workflow_status"] == "withheld"


@pytest.mark.asyncio
async def test_worker_recovers_queued_job_after_start() -> None:
    get_goal_sync_job_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal = GoalContract(
        goal_id=uuid4(),
        title="Read 20 books",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "books_read", "target": 20},
        deadline=datetime.now(UTC) + timedelta(days=60),
        state_dimensions=["books_read"],
    )
    await app.state.agent_workflow._inner._deps.goals._repository.create(goal, owner)
    store = get_goal_sync_job_store()
    queued = await store.enqueue(owner, goal.goal_id)
    stop = asyncio.Event()
    worker = asyncio.create_task(goal_sync_worker(app, stop))
    try:
        for _ in range(20):
            if (await store.get(owner, goal.goal_id, queued.id)).status == "completed":
                break
            await asyncio.sleep(0.05)
        assert (await store.get(owner, goal.goal_id, queued.id)).status == "completed"
    finally:
        stop.set()
        await worker
