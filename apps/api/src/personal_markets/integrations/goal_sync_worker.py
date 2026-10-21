"""Single-process dispatcher for persisted goal source sync jobs."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from personal_markets.core.config import get_settings
from personal_markets.integrations.goal_sync_jobs import GoalSyncJob, get_goal_sync_job_store
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.wiring import get_integration_repository, integration_gateway_for

_log = structlog.get_logger(__name__)


async def execute_goal_sync_job(application: Any, job: GoalSyncJob) -> None:
    store = get_goal_sync_job_store()
    deps = application.state.agent_workflow._inner._deps
    receipt: dict[str, Any] = {
        **job.receipt,
        "run_id": str(job.id),
        "started_at": job.started_at.isoformat() if job.started_at else None,
    }
    service = GoalSyncService(
        settings=get_settings(),
        gateway=integration_gateway_for(job.owner_id),
        repository=get_integration_repository(),
        goals=deps.goals,
        workflow=application.state.agent_workflow,
        evidence=deps.evidence,
        owner_id=job.owner_id,
        job_id=job.id,
        replay_job_ids=[UUID(value) for value in job.receipt.get("replay_job_ids", [])],
    )

    async def stage(status: str, values: dict[str, Any]) -> None:
        receipt.update(values)
        await store.update(job.id, status=status, receipt=receipt.copy())

    try:
        async with asyncio.timeout(240):
            outcome = await service.sync_goal_sources(str(job.goal_id), on_stage=stage)
        if isinstance(outcome, dict):
            receipt.update(outcome)
            failed = outcome.get("status") not in {"no_new_records", "no_recipes"}
        else:
            receipt["workflow_thread_id"] = str(outcome.thread_id)
            receipt["workflow_status"] = outcome.status
            receipt["observations"] = len(outcome.evidence)
            receipt["forecast_result"] = (
                outcome.pricing.model_dump(mode="json") if outcome.pricing else None
            )
            # An irrelevant source observation is a successful read with no
            # forecast change, not a failed provider sync.
            failed = outcome.status not in {"completed", "unchanged"}
        receipt["completed_at"] = datetime.now(UTC).isoformat()
        await store.update(
            job.id,
            status="failed" if failed else "completed",
            receipt=receipt,
            finished_at=datetime.now(UTC),
            error="Goal update failed. Review the run before retrying." if failed else None,
        )
    except TimeoutError:
        await store.update(
            job.id,
            status="timed_out",
            receipt=receipt,
            finished_at=datetime.now(UTC),
            error="Sync took too long. Review the result before retrying.",
        )
    except Exception as error:  # noqa: BLE001
        _log.exception("goal_source_sync_job_failed", run_id=str(job.id), goal_id=str(job.goal_id))
        receipt["error_type"] = type(error).__name__
        public_error = (
            "Source access failed. Reconnect this source and try again."
            if any(
                word in str(error).lower()
                for word in ("access denied", "permission", "unauthorized")
            )
            else "Source sync failed. Review the connection and try again."
        )
        await store.update(
            job.id,
            status="failed",
            receipt=receipt,
            finished_at=datetime.now(UTC),
            error=public_error,
        )


async def goal_sync_worker(application: Any, stop: asyncio.Event) -> None:
    store = get_goal_sync_job_store()
    while not stop.is_set():
        try:
            await store.expire_stranded()
            job = await store.claim()
            if job is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=2)
                continue
            await execute_goal_sync_job(application, job)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _log.exception("goal_source_sync_worker_error")
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=5)
