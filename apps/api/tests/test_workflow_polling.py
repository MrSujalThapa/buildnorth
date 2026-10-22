from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.persistence.agent_store import InMemoryThreadStore, running_thread_expired
from personal_markets.ports import WorkflowSnapshot
from personal_markets.wiring import PersistingWorkflow


def test_running_thread_expires_only_after_inference_timeout_and_grace() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    assert not running_thread_expired(now - timedelta(seconds=180), timeout_seconds=120, now=now)
    assert running_thread_expired(now - timedelta(seconds=181), timeout_seconds=120, now=now)


class StaleInnerWorkflow:
    def __init__(self, snapshot: WorkflowSnapshot) -> None:
        self.snapshot_value = snapshot
        self.calls = 0

    async def snapshot(self, thread_id):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.snapshot_value


@pytest.mark.asyncio
async def test_poll_cannot_revive_failed_background_workflow() -> None:
    thread_id = uuid4()
    stored = WorkflowSnapshot(
        thread_id=thread_id, kind="create_goal", status="failed", current_step="failed"
    )
    stale = stored.model_copy(update={"status": "running", "current_step": "parse_request"})
    threads = InMemoryThreadStore()
    await threads.upsert(stored)
    inner = StaleInnerWorkflow(stale)
    workflow = PersistingWorkflow(inner, threads)  # type: ignore[arg-type]

    result = await workflow.snapshot(thread_id)

    assert result.status == "failed"
    assert inner.calls == 0
    assert (await threads.get(thread_id)) == stored


@pytest.mark.asyncio
async def test_poll_does_not_write_running_checkpoint() -> None:
    thread_id = uuid4()
    running = WorkflowSnapshot(
        thread_id=thread_id, kind="create_goal", status="running", current_step="parse_request"
    )
    threads = InMemoryThreadStore()
    await threads.upsert(running)
    inner = StaleInnerWorkflow(running.model_copy(update={"current_step": "interpret_goal"}))
    workflow = PersistingWorkflow(inner, threads)  # type: ignore[arg-type]

    result = await workflow.snapshot(thread_id)

    assert result.current_step == "interpret_goal"
    assert (await threads.get(thread_id)) == running
