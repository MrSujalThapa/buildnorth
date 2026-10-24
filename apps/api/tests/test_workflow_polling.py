import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import TransientProviderError
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.persistence.agent_store import InMemoryThreadStore, running_thread_expired
from personal_markets.ports import ResumePayload, WorkflowSnapshot
from personal_markets.wiring import PersistingWorkflow, get_agent_workflow


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


class FailingInnerWorkflow(StaleInnerWorkflow):
    async def resume(self, thread_id: UUID, payload: ResumePayload) -> WorkflowSnapshot:
        del thread_id, payload
        raise TransientProviderError("provider timed out")


class RoutingFailingInnerWorkflow(FailingInnerWorkflow):
    def __init__(self, before: WorkflowSnapshot, after: WorkflowSnapshot) -> None:
        super().__init__(before)
        self.after = after

    async def resume(self, thread_id: UUID, payload: ResumePayload) -> WorkflowSnapshot:
        self.snapshot_value = self.after
        return await super().resume(thread_id, payload)


def _saved_goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Earn 80% in a course",
        goal_type=GoalType.THRESHOLD,
        success_definition={"target": 80},
        deadline=datetime.now(UTC) + timedelta(days=60),
        state_dimensions=["course_grade"],
    )


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


@pytest.mark.asyncio
async def test_sync_provider_timeout_returns_saved_goal_and_persists_failed_state() -> None:
    thread_id = uuid4()
    goal = _saved_goal()
    proposal = WorkflowSnapshot(
        thread_id=thread_id, kind="create_goal", status="needs_input", current_step="confirm_goal"
    )
    committed = proposal.model_copy(
        update={
            "status": "running", "current_step": "normalize_evidence", "goal": goal,
            "debug": {"goal_committed": True},
        }
    )
    threads = InMemoryThreadStore()
    await threads.upsert(proposal)
    workflow = PersistingWorkflow(FailingInnerWorkflow(committed), threads)  # type: ignore[arg-type]

    result = await workflow.resume(thread_id, ResumePayload(confirmed=True))

    assert result.status == "failed"
    assert result.goal == goal
    assert result.interrupt is None
    assert "Review the saved goal" in result.progress[-1]
    assert (await workflow.snapshot(thread_id)) == result


@pytest.mark.asyncio
async def test_background_provider_failure_keeps_latest_committed_goal() -> None:
    thread_id = uuid4()
    goal = _saved_goal()
    proposal = WorkflowSnapshot(
        thread_id=thread_id, kind="create_goal", status="needs_input", current_step="confirm_goal"
    )
    committed = proposal.model_copy(
        update={
            "status": "running", "current_step": "normalize_evidence", "goal": goal,
            "debug": {"goal_committed": True},
        }
    )
    threads = InMemoryThreadStore()
    await threads.upsert(proposal)
    workflow = PersistingWorkflow(FailingInnerWorkflow(committed), threads)  # type: ignore[arg-type]
    await workflow.mark_running(thread_id)

    await workflow.resume_later(thread_id, ResumePayload(confirmed=True))

    result = await workflow.snapshot(thread_id)
    assert result.status == "failed"
    assert result.goal == goal


def test_resume_http_returns_failed_snapshot_with_saved_goal() -> None:
    app = isolated_app()
    principal = app.state.auth_bypass_principal
    thread_id = uuid4()
    goal = _saved_goal()
    proposal = WorkflowSnapshot(
        thread_id=thread_id,
        kind="create_goal",
        status="needs_input",
        current_step="confirm_goal",
        debug={"user_id": str(principal.user_id)},
    )
    committed = proposal.model_copy(
        update={
            "status": "running", "current_step": "normalize_evidence", "goal": goal,
            "debug": {"user_id": str(principal.user_id), "goal_committed": True},
        }
    )
    threads = InMemoryThreadStore()
    asyncio.run(threads.upsert(proposal))
    workflow = PersistingWorkflow(
        RoutingFailingInnerWorkflow(proposal, committed), threads  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_agent_workflow] = lambda: workflow

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "failed"
        assert response.json()["goal"]["goal_id"] == str(goal.goal_id)
        polled = client.get(f"/api/v1/agent/threads/{thread_id}")
        assert polled.status_code == 200
        assert polled.json()["goal"]["goal_id"] == str(goal.goal_id)
