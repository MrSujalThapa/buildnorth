"""Persisted, owner-scoped goal source sync jobs.

A claimed job is never replayed after process loss: provider reads may already have
completed, and the following agent workflow may be billable. Stranded jobs are
marked timed out so the user can decide whether to retry.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.core.config import get_settings
from personal_markets.persistence.database import create_engine, transaction

JOB_DEADLINE = timedelta(minutes=4)
ACTIVE = {"queued", "fetching_sources", "processing_evidence", "updating_forecast"}
TERMINAL = {"completed", "failed", "timed_out"}


class GoalSyncJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    goal_id: UUID
    status: str = "queued"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class InMemoryGoalSyncJobStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, GoalSyncJob] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, owner_id: UUID, goal_id: UUID) -> GoalSyncJob:
        async with self._lock:
            active = [
                job
                for job in self._jobs.values()
                if job.owner_id == owner_id and job.goal_id == goal_id and job.status in ACTIVE
            ]
            if active:
                return max(active, key=lambda job: job.created_at)
            latest = max(
                (
                    job
                    for job in self._jobs.values()
                    if job.owner_id == owner_id and job.goal_id == goal_id
                ),
                key=lambda job: job.created_at,
                default=None,
            )
            replay_ids = _replay_ids(latest)
            job = GoalSyncJob(
                owner_id=owner_id,
                goal_id=goal_id,
                receipt={"replay_job_ids": replay_ids} if replay_ids else {},
            )
            self._jobs[job.id] = job
            return job

    async def latest(self, owner_id: UUID, goal_id: UUID) -> GoalSyncJob | None:
        jobs = [
            job
            for job in self._jobs.values()
            if job.owner_id == owner_id and job.goal_id == goal_id
        ]
        return max(jobs, key=lambda job: job.created_at) if jobs else None

    async def get(self, owner_id: UUID, goal_id: UUID, job_id: UUID) -> GoalSyncJob | None:
        job = self._jobs.get(job_id)
        return job if job and job.owner_id == owner_id and job.goal_id == goal_id else None

    async def claim(self) -> GoalSyncJob | None:
        async with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.status == "queued"),
                key=lambda job: job.created_at,
            )
            if not queued:
                return None
            return await self._set(
                queued[0].id, status="fetching_sources", started_at=datetime.now(UTC)
            )

    async def update(self, job_id: UUID, **changes: Any) -> GoalSyncJob:
        async with self._lock:
            return await self._set(job_id, **changes)

    async def _set(self, job_id: UUID, **changes: Any) -> GoalSyncJob:
        job = self._jobs[job_id].model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        self._jobs[job_id] = job
        return job

    async def expire_stranded(self) -> int:
        now = datetime.now(UTC)
        count = 0
        async with self._lock:
            for job in list(self._jobs.values()):
                if (
                    job.status in ACTIVE - {"queued"}
                    and job.started_at
                    and now - job.started_at >= JOB_DEADLINE
                ):
                    await self._set(
                        job.id,
                        status="timed_out",
                        finished_at=now,
                        error="Sync was interrupted. Review the result before retrying.",
                    )
                    count += 1
        return count


class PostgresGoalSyncJobStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    def _row(row: Any) -> GoalSyncJob:
        return GoalSyncJob.model_validate(dict(row))

    async def enqueue(self, owner_id: UUID, goal_id: UUID) -> GoalSyncJob:
        from json import dumps

        async with transaction(self._engine) as connection:
            previous = (
                (
                    await connection.execute(
                        text("""
                    select * from goal_sync_jobs where owner_id = :owner_id and goal_id = :goal_id
                    order by created_at desc limit 1
                    """),
                        {"owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .first()
            )
            replay_ids = _replay_ids(self._row(previous) if previous else None)
            created = (
                (
                    await connection.execute(
                        text("""
                insert into goal_sync_jobs (id, owner_id, goal_id, status, receipt)
                values (:id, :owner_id, :goal_id, 'queued', cast(:receipt as jsonb))
                on conflict do nothing returning *
            """),
                        {
                            "id": uuid4(),
                            "owner_id": owner_id,
                            "goal_id": goal_id,
                            "receipt": dumps({"replay_job_ids": replay_ids} if replay_ids else {}),
                        },
                    )
                )
                .mappings()
                .first()
            )
            if created:
                return self._row(created)
            existing = (
                (
                    await connection.execute(
                        text("""
                select * from goal_sync_jobs
                where owner_id = :owner_id and goal_id = :goal_id
                  and status in (
                    'queued', 'fetching_sources', 'processing_evidence', 'updating_forecast'
                  )
                order by created_at desc limit 1
            """),
                        {"owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                raise RuntimeError("Could not enqueue source sync")
            return self._row(existing)

    async def latest(self, owner_id: UUID, goal_id: UUID) -> GoalSyncJob | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                select * from goal_sync_jobs where owner_id = :owner_id and goal_id = :goal_id
                order by created_at desc limit 1
            """),
                        {"owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .first()
            )
            return self._row(row) if row else None

    async def get(self, owner_id: UUID, goal_id: UUID, job_id: UUID) -> GoalSyncJob | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                select * from goal_sync_jobs
                where id = :id and owner_id = :owner_id and goal_id = :goal_id
            """),
                        {"id": job_id, "owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .first()
            )
            return self._row(row) if row else None

    async def claim(self) -> GoalSyncJob | None:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                with next_job as (
                  select id from goal_sync_jobs where status = 'queued'
                  order by created_at for update skip locked limit 1
                )
                update goal_sync_jobs set status = 'fetching_sources',
                  started_at = now(), updated_at = now()
                where id in (select id from next_job) returning *
            """)
                    )
                )
                .mappings()
                .first()
            )
            return self._row(row) if row else None

    async def update(self, job_id: UUID, **changes: Any) -> GoalSyncJob:
        allowed = {"status", "receipt", "error", "finished_at"}
        if set(changes) - allowed:
            raise ValueError("Unsupported sync job update")
        from json import dumps

        columns = [f"{key} = :{key}" for key in changes if key != "receipt"]
        if "receipt" in changes:
            columns.append("receipt = cast(:receipt as jsonb)")
            changes["receipt"] = dumps(changes["receipt"])
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "update goal_sync_jobs set "
                            + ", ".join(columns)
                            + ", updated_at = now() where id = :id returning *"
                        ),
                        {"id": job_id, **changes},
                    )
                )
                .mappings()
                .one()
            )
            return self._row(row)

    async def expire_stranded(self) -> int:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("""
                update goal_sync_jobs set status = 'timed_out', finished_at = now(),
                  updated_at = now(),
                  error = 'Sync was interrupted. Review the result before retrying.'
                where status in ('fetching_sources', 'processing_evidence', 'updating_forecast')
                  and started_at < now() - interval '4 minutes'
            """)
            )
            return result.rowcount


@lru_cache
def get_goal_sync_job_store() -> InMemoryGoalSyncJobStore | PostgresGoalSyncJobStore:
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresGoalSyncJobStore(create_engine(settings.database_url))
    return InMemoryGoalSyncJobStore()


def _replay_ids(previous: GoalSyncJob | None) -> list[str]:
    if previous is None or previous.status not in {"failed", "timed_out"}:
        return []
    return [*previous.receipt.get("replay_job_ids", []), str(previous.id)]
