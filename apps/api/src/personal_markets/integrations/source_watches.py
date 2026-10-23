"""Explicit monitoring consent and durable scheduling for approved source recipes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.core.config import get_settings
from personal_markets.integrations.goal_sync_jobs import get_goal_sync_job_store
from personal_markets.persistence.database import autocommit_connection, create_engine, transaction


class SourceWatch(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    goal_id: UUID
    plugin_connection_id: UUID
    plugin_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    scope: Literal["resource", "parent"] = "resource"
    status: Literal["active", "paused", "revoked"] = "active"
    interval_minutes: int = Field(default=60, ge=15, le=10080)
    next_check_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    cursor_value: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InMemorySourceWatchStore:
    def __init__(self) -> None:
        self._rows: dict[UUID, SourceWatch] = {}
        self._lock = asyncio.Lock()

    async def save(self, watch: SourceWatch) -> SourceWatch:
        async with self._lock:
            for previous in self._rows.values():
                if (
                    previous.owner_id == watch.owner_id
                    and previous.goal_id == watch.goal_id
                    and previous.plugin_connection_id == watch.plugin_connection_id
                    and previous.resource_id == watch.resource_id
                    and previous.scope == watch.scope
                ):
                    watch = watch.model_copy(
                        update={"id": previous.id, "created_at": previous.created_at}
                    )
                    break
            self._rows[watch.id] = watch
            return watch

    async def list_for_goal(self, owner_id: UUID, goal_id: UUID) -> list[SourceWatch]:
        return [w for w in self._rows.values() if w.owner_id == owner_id and w.goal_id == goal_id]

    async def active_resource_uris(self, owner_id: UUID, goal_id: UUID) -> set[str]:
        return {
            f"composio://{w.plugin_id}/{w.resource_id}"
            for w in await self.list_for_goal(owner_id, goal_id)
            if w.status == "active"
        }

    async def set_status(
        self, owner_id: UUID, goal_id: UUID, watch_id: UUID, status: str
    ) -> SourceWatch | None:
        async with self._lock:
            watch = self._rows.get(watch_id)
            if watch is None or watch.owner_id != owner_id or watch.goal_id != goal_id:
                return None
            watch = watch.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
            self._rows[watch.id] = watch
            return watch

    async def record_result(
        self, owner_id: UUID, goal_id: UUID, uris: list[str], *, error: str | None
    ) -> None:
        now = datetime.now(UTC)
        selected = set(uris)
        async with self._lock:
            for watch in list(self._rows.values()):
                if (
                    watch.owner_id == owner_id
                    and watch.goal_id == goal_id
                    and watch.status == "active"
                    and f"composio://{watch.plugin_id}/{watch.resource_id}" in selected
                ):
                    self._rows[watch.id] = watch.model_copy(update={
                        "last_success_at": now if error is None else watch.last_success_at,
                        "last_error": error,
                        "updated_at": now,
                    })

    async def enqueue_due(self, limit: int = 25) -> int:
        now = datetime.now(UTC)
        count = 0
        async with self._lock:
            due = sorted(
                (w for w in self._rows.values() if w.status == "active" and w.next_check_at <= now),
                key=lambda w: w.next_check_at,
            )[:limit]
            for watch in due:
                jobs = get_goal_sync_job_store()
                active = await jobs.latest(watch.owner_id, watch.goal_id)
                if active is not None and active.status in {
                    "queued", "fetching_sources", "processing_evidence", "updating_forecast"
                }:
                    continue
                job = await jobs.enqueue(watch.owner_id, watch.goal_id)
                uri = f"composio://{watch.plugin_id}/{watch.resource_id}"
                uris = set(job.receipt.get("watch_resource_uris", []))
                await jobs.update(
                    job.id,
                    receipt={
                        **job.receipt,
                        "origin": "watch",
                        "watch_resource_uris": sorted(uris | {uri}),
                    },
                )
                self._rows[watch.id] = watch.model_copy(
                    update={
                        "last_checked_at": now,
                        "next_check_at": now + timedelta(minutes=watch.interval_minutes),
                        "updated_at": now,
                    }
                )
                count += 1
        return count


class PostgresSourceWatchStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, watch: SourceWatch) -> SourceWatch:
        async with transaction(self._engine) as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                insert into source_watches
                  (id, owner_id, goal_id, plugin_connection_id, plugin_id, resource_id, scope,
                   status, interval_minutes, next_check_at)
                values (:id, :owner_id, :goal_id, :plugin_connection_id, :plugin_id, :resource_id,
                        :scope, :status, :interval_minutes, :next_check_at)
                on conflict (owner_id, goal_id, plugin_connection_id, resource_id, scope)
                do update set status = excluded.status,
                  interval_minutes = excluded.interval_minutes,
                  next_check_at = excluded.next_check_at, updated_at = now()
                returning *
            """),
                        watch.model_dump(),
                    )
                )
                .mappings()
                .one()
            )
            return SourceWatch.model_validate(dict(row))

    async def list_for_goal(self, owner_id: UUID, goal_id: UUID) -> list[SourceWatch]:
        async with autocommit_connection(self._engine) as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                select * from source_watches where owner_id = :owner_id and goal_id = :goal_id
                order by created_at
            """),
                        {"owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .all()
            )
            return [SourceWatch.model_validate(dict(row)) for row in rows]

    async def active_resource_uris(self, owner_id: UUID, goal_id: UUID) -> set[str]:
        async with autocommit_connection(self._engine) as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                select plugin_id, resource_id from source_watches
                where owner_id = :owner_id and goal_id = :goal_id and status = 'active'
            """),
                        {"owner_id": owner_id, "goal_id": goal_id},
                    )
                )
                .mappings()
                .all()
            )
            return {f"composio://{r['plugin_id']}/{r['resource_id']}" for r in rows}

    async def set_status(
        self, owner_id: UUID, goal_id: UUID, watch_id: UUID, status: str
    ) -> SourceWatch | None:
        async with transaction(self._engine) as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                update source_watches set status = :status, updated_at = now()
                where id = :id and owner_id = :owner_id and goal_id = :goal_id returning *
            """),
                        {
                            "id": watch_id,
                            "owner_id": owner_id,
                            "goal_id": goal_id,
                            "status": status,
                        },
                    )
                )
                .mappings()
                .first()
            )
            return SourceWatch.model_validate(dict(row)) if row else None

    async def record_result(
        self, owner_id: UUID, goal_id: UUID, uris: list[str], *, error: str | None
    ) -> None:
        async with transaction(self._engine) as conn:
            for uri in set(uris):
                if not uri.startswith("composio://") or "/" not in uri[11:]:
                    continue
                plugin_id, resource_id = uri[11:].split("/", 1)
                await conn.execute(
                    text("""
                    update source_watches set
                      last_success_at = case when cast(:error as text) is null then now()
                        else last_success_at end,
                      last_error = :error, updated_at = now()
                    where owner_id = :owner_id and goal_id = :goal_id
                      and plugin_id = :plugin_id and resource_id = :resource_id
                      and status = 'active'
                    """),
                    {
                        "owner_id": owner_id, "goal_id": goal_id,
                        "plugin_id": plugin_id, "resource_id": resource_id,
                        "error": error,
                    },
                )

    async def enqueue_due(self, limit: int = 25) -> int:
        # Advance checkpoints only when a new job is durably queued. An active
        # manual/watch job can otherwise cause ON CONFLICT DO NOTHING to drop a poll.
        async with transaction(self._engine) as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                select id, owner_id, goal_id from source_watches
                where status = 'active' and next_check_at <= now()
                order by next_check_at for update skip locked limit :limit
            """),
                        {"limit": limit},
                    )
                )
                .mappings()
                .all()
            )
            grouped: dict[tuple[UUID, UUID], list[UUID]] = {}
            for row in rows:
                grouped.setdefault((row["owner_id"], row["goal_id"]), []).append(row["id"])
            enqueued = 0
            for (owner_id, goal_id), watch_ids in grouped.items():
                inserted = (
                    await conn.execute(
                    text("""
                    insert into goal_sync_jobs (id, owner_id, goal_id, status, receipt)
                    select :id, :owner_id, :goal_id, 'queued',
                      jsonb_build_object('origin', 'watch', 'watch_resource_uris',
                        coalesce((select jsonb_agg(distinct
                          ('composio://' || sw.plugin_id || '/' || sw.resource_id))
                          from source_watches sw
                          where sw.owner_id = :owner_id and sw.goal_id = :goal_id
                            and sw.status = 'active'), '[]'::jsonb))
                    on conflict do nothing returning id
                """),
                    {"id": uuid4(), "owner_id": owner_id, "goal_id": goal_id},
                    )
                ).scalar_one_or_none()
                if inserted is None:
                    continue
                for watch_id in watch_ids:
                    await conn.execute(
                        text("""
                        update source_watches set last_checked_at = now(),
                          next_check_at = now() + make_interval(mins => interval_minutes),
                          updated_at = now() where id = :id
                        """),
                        {"id": watch_id},
                    )
                enqueued += len(watch_ids)
            return enqueued


@lru_cache
def get_source_watch_store() -> InMemorySourceWatchStore | PostgresSourceWatchStore:
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresSourceWatchStore(create_engine(settings.database_url))
    return InMemorySourceWatchStore()
