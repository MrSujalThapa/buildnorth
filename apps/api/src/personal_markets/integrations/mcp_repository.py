from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.integrations.mcp_domain import (
    ConnectionType,
    GoalSyncRecipeRecord,
    PluginConnectionRecord,
    RawSourceRecord,
    ReadCapabilityRecord,
    SyncCursorRecord,
    SyncRecipeRecord,
    SyncRecipeStep,
    SyncRunRecord,
)
from personal_markets.persistence.database import autocommit_connection, transaction


class InMemoryIntegrationRepository:
    def __init__(self) -> None:
        self.connections: dict[UUID, PluginConnectionRecord] = {}
        self.capabilities: dict[UUID, list[ReadCapabilityRecord]] = {}
        self.recipes: dict[UUID, SyncRecipeRecord] = {}
        self.cursors: dict[tuple[UUID, str], SyncCursorRecord] = {}
        self.runs: dict[UUID, SyncRunRecord] = {}
        self.raw_records: list[RawSourceRecord] = []
        self.goal_recipes: dict[tuple[UUID, str], GoalSyncRecipeRecord] = {}

    async def upsert_connection(self, record: PluginConnectionRecord) -> PluginConnectionRecord:
        existing = await self.get_connection(record.user_id, record.plugin_id)
        if existing is not None:
            record = record.model_copy(update={"id": existing.id})
        self.connections[record.id] = record
        return record

    async def get_connection(self, user_id: UUID, plugin_id: str) -> PluginConnectionRecord | None:
        for item in self.connections.values():
            if item.user_id == user_id and item.plugin_id == plugin_id:
                return item
        return None

    async def list_connections(self, user_id: UUID) -> list[PluginConnectionRecord]:
        return [item for item in self.connections.values() if item.user_id == user_id]

    async def save_capabilities(
        self, connection_id: UUID, rows: list[ReadCapabilityRecord]
    ) -> list[ReadCapabilityRecord]:
        self.capabilities[connection_id] = rows
        return rows

    async def list_capabilities(self, connection_id: UUID) -> list[ReadCapabilityRecord]:
        return self.capabilities.get(connection_id, [])

    async def save_recipe(self, recipe: SyncRecipeRecord) -> SyncRecipeRecord:
        self.recipes[recipe.plugin_connection_id] = recipe
        return recipe

    async def get_recipe(self, connection_id: UUID) -> SyncRecipeRecord | None:
        return self.recipes.get(connection_id)

    async def get_cursor(self, connection_id: UUID, capability_id: str) -> SyncCursorRecord | None:
        return self.cursors.get((connection_id, capability_id))

    async def put_cursor(self, cursor: SyncCursorRecord) -> None:
        self.cursors[(cursor.plugin_connection_id, cursor.capability_id)] = cursor

    async def start_run(self, connection_id: UUID) -> SyncRunRecord:
        run = SyncRunRecord(
            id=uuid4(),
            plugin_connection_id=connection_id,
            status="running",
            started_at=datetime.now(UTC),
        )
        self.runs[run.id] = run
        return run

    async def finish_run(self, run_id: UUID, *, status: str, records_read: int, records_new: int, error: str | None = None) -> SyncRunRecord:
        run = self.runs[run_id]
        updated = run.model_copy(
            update={
                "status": status,
                "finished_at": datetime.now(UTC),
                "records_read": records_read,
                "records_new": records_new,
                "error": error,
            }
        )
        self.runs[run_id] = updated
        return updated

    async def append_raw_records(self, rows: list[RawSourceRecord]) -> list[RawSourceRecord]:
        existing = {(item.plugin_connection_id, item.external_id) for item in self.raw_records}
        inserted: list[RawSourceRecord] = []
        for row in rows:
            key = (row.plugin_connection_id, row.external_id)
            if key in existing:
                continue
            self.raw_records.append(row)
            existing.add(key)
            inserted.append(row)
        return inserted

    async def list_job_raw_records(
        self, owner_id: UUID, job_ids: list[UUID]
    ) -> list[RawSourceRecord]:
        requested = {str(job_id) for job_id in job_ids}
        return [
            row for row in self.raw_records
            if row.cursor_context.get("user_id") == str(owner_id)
            and row.cursor_context.get("goal_sync_job_id") in requested
        ]

    async def update_connection(self, connection_id: UUID, **fields: Any) -> PluginConnectionRecord:
        record = self.connections[connection_id]
        updated = record.model_copy(update=fields)
        self.connections[connection_id] = updated
        return updated

    async def delete_connection(self, connection_id: UUID) -> None:
        self.connections.pop(connection_id, None)
        self.capabilities.pop(connection_id, None)
        self.recipes.pop(connection_id, None)

    async def save_goal_recipe(self, recipe: GoalSyncRecipeRecord) -> GoalSyncRecipeRecord:
        self.goal_recipes[(recipe.goal_id, recipe.plugin_id)] = recipe
        return recipe

    async def list_goal_recipes(self, goal_id: UUID) -> list[GoalSyncRecipeRecord]:
        return [item for (gid, _), item in self.goal_recipes.items() if gid == goal_id]

    async def get_goal_recipe(self, goal_id: UUID, plugin_id: str) -> GoalSyncRecipeRecord | None:
        return self.goal_recipes.get((goal_id, plugin_id))


class PostgresIntegrationRepository(InMemoryIntegrationRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__()
        self._engine = engine

    @staticmethod
    def _row_to_connection(row: dict[str, Any]) -> PluginConnectionRecord:
        return PluginConnectionRecord(
            id=row["id"],
            user_id=row["user_id"],
            plugin_id=row["plugin_id"],
            connection_type=ConnectionType(row["connection_type"]),
            gateway_provider=row["gateway_provider"],
            transport=row["transport"],
            auth_ref=row["auth_ref"],
            status=row["status"],
            account_metadata=row["account_metadata_json"] or {},
            created_at=row["created_at"],
            last_verified_at=row["last_verified_at"],
            last_sync_at=row["last_sync_at"],
        )

    async def get_connection(self, user_id: UUID, plugin_id: str) -> PluginConnectionRecord | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from plugin_connections where user_id = :user_id and plugin_id = :plugin_id"
                        ),
                        {"user_id": user_id, "plugin_id": plugin_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._row_to_connection(dict(row)) if row else None

    async def list_connections(self, user_id: UUID) -> list[PluginConnectionRecord]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text("select * from plugin_connections where user_id = :user_id"),
                    {"user_id": user_id},
                )
            ).mappings()
        return [self._row_to_connection(dict(row)) for row in rows]

    async def save_capabilities(
        self, connection_id: UUID, rows: list[ReadCapabilityRecord]
    ) -> list[ReadCapabilityRecord]:
        async with transaction(self._engine) as connection:
            for row in rows:
                await connection.execute(
                    text("""
                    insert into read_capabilities (
                      id, plugin_connection_id, capability_id, label, operation, tool_name,
                      resource_uri, input_schema_json, approved
                    ) values (
                      :id, :plugin_connection_id, :capability_id, :label, :operation, :tool_name,
                      :resource_uri, cast(:input_schema as jsonb), :approved
                    ) on conflict (plugin_connection_id, capability_id) do update set
                      label = excluded.label,
                      operation = excluded.operation,
                      tool_name = excluded.tool_name,
                      input_schema_json = excluded.input_schema_json,
                      approved = excluded.approved
                    """),
                    {
                        "id": row.id,
                        "plugin_connection_id": connection_id,
                        "capability_id": row.capability_id,
                        "label": row.label,
                        "operation": row.operation,
                        "tool_name": row.tool_name,
                        "resource_uri": row.resource_uri,
                        "input_schema": json.dumps(row.input_schema),
                        "approved": row.approved,
                    },
                )
        return rows

    async def list_capabilities(self, connection_id: UUID) -> list[ReadCapabilityRecord]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from read_capabilities where plugin_connection_id = :plugin_connection_id"
                    ),
                    {"plugin_connection_id": connection_id},
                )
            ).mappings()
        return [
            ReadCapabilityRecord(
                id=row["id"],
                plugin_connection_id=row["plugin_connection_id"],
                capability_id=row["capability_id"],
                label=row["label"],
                operation=row["operation"],
                tool_name=row["tool_name"],
                resource_uri=row["resource_uri"],
                input_schema=row["input_schema_json"] or {},
                approved=row["approved"],
            )
            for row in rows
        ]

    async def save_recipe(self, recipe: SyncRecipeRecord) -> SyncRecipeRecord:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into sync_recipes (id, plugin_connection_id, recipe_version, steps_json)
                values (:id, :plugin_connection_id, :recipe_version, cast(:steps as jsonb))
                on conflict (plugin_connection_id, recipe_version) do update set
                  steps_json = excluded.steps_json,
                  validated_at = now()
                """),
                {
                    "id": recipe.id,
                    "plugin_connection_id": recipe.plugin_connection_id,
                    "recipe_version": recipe.recipe_version,
                    "steps": json.dumps([step.model_dump(mode="json") for step in recipe.steps]),
                },
            )
        return recipe

    async def get_recipe(self, connection_id: UUID) -> SyncRecipeRecord | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from sync_recipes where plugin_connection_id = :id order by recipe_version desc limit 1"
                        ),
                        {"id": connection_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        steps = [SyncRecipeStep.model_validate(item) for item in row["steps_json"]]
        return SyncRecipeRecord(
            id=row["id"],
            plugin_connection_id=row["plugin_connection_id"],
            recipe_version=row["recipe_version"],
            steps=steps,
        )

    async def get_cursor(self, connection_id: UUID, capability_id: str) -> SyncCursorRecord | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from sync_cursors where plugin_connection_id = :id and capability_id = :capability_id"
                        ),
                        {"id": connection_id, "capability_id": capability_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return SyncCursorRecord(
            plugin_connection_id=row["plugin_connection_id"],
            capability_id=row["capability_id"],
            cursor_value=row["cursor_value"],
            updated_at=row["updated_at"],
        )

    async def put_cursor(self, cursor: SyncCursorRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into sync_cursors (id, plugin_connection_id, capability_id, cursor_value, updated_at)
                values (gen_random_uuid(), :plugin_connection_id, :capability_id, :cursor_value, :updated_at)
                on conflict (plugin_connection_id, capability_id) do update set
                  cursor_value = excluded.cursor_value,
                  updated_at = excluded.updated_at
                """),
                {
                    "plugin_connection_id": cursor.plugin_connection_id,
                    "capability_id": cursor.capability_id,
                    "cursor_value": cursor.cursor_value,
                    "updated_at": cursor.updated_at,
                },
            )

    async def start_run(self, connection_id: UUID) -> SyncRunRecord:
        run = SyncRunRecord(
            id=uuid4(),
            plugin_connection_id=connection_id,
            status="running",
            started_at=datetime.now(UTC),
        )
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into sync_runs (id, plugin_connection_id, status, started_at)
                values (:id, :plugin_connection_id, :status, :started_at)
                """),
                {
                    "id": run.id,
                    "plugin_connection_id": connection_id,
                    "status": run.status,
                    "started_at": run.started_at,
                },
            )
        return run

    async def finish_run(
        self, run_id: UUID, *, status: str, records_read: int, records_new: int, error: str | None = None
    ) -> SyncRunRecord:
        finished_at = datetime.now(UTC)
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                update sync_runs
                set status = :status, finished_at = :finished_at, records_read = :records_read,
                    records_new = :records_new, error = :error
                where id = :id
                """),
                {
                    "id": run_id,
                    "status": status,
                    "finished_at": finished_at,
                    "records_read": records_read,
                    "records_new": records_new,
                    "error": error,
                },
            )
        return SyncRunRecord(
            id=run_id,
            plugin_connection_id=UUID(int=0),
            status=status,
            started_at=finished_at,
            finished_at=finished_at,
            records_read=records_read,
            records_new=records_new,
            error=error,
        )

    async def update_connection(self, connection_id: UUID, **fields: Any) -> PluginConnectionRecord:
        sets = []
        params: dict[str, Any] = {"id": connection_id}
        for key, value in fields.items():
            if key == "last_sync_at":
                sets.append("last_sync_at = :last_sync_at")
                params["last_sync_at"] = value
            if key == "status":
                sets.append("status = :status")
                params["status"] = value
        if sets:
            async with transaction(self._engine) as connection:
                await connection.execute(
                    text(f"update plugin_connections set {', '.join(sets)} where id = :id"),
                    params,
                )
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from plugin_connections where id = :id"),
                        {"id": connection_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        assert row is not None
        return self._row_to_connection(dict(row))

    async def delete_connection(self, connection_id: UUID) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("delete from plugin_connections where id = :id"),
                {"id": connection_id},
            )

    async def upsert_connection(self, record: PluginConnectionRecord) -> PluginConnectionRecord:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into plugin_connections (
                  id, user_id, plugin_id, connection_type, gateway_provider, transport,
                  auth_ref, status, account_metadata_json, created_at, last_verified_at, last_sync_at
                ) values (
                  :id, :user_id, :plugin_id, :connection_type, :gateway_provider, :transport,
                  :auth_ref, :status, cast(:account_metadata as jsonb), :created_at, :last_verified_at, :last_sync_at
                ) on conflict (user_id, plugin_id) do update set
                  status = excluded.status,
                  gateway_provider = excluded.gateway_provider,
                  auth_ref = excluded.auth_ref,
                  account_metadata_json = excluded.account_metadata_json,
                  last_verified_at = excluded.last_verified_at,
                  last_sync_at = excluded.last_sync_at
                """),
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "plugin_id": record.plugin_id,
                    "connection_type": record.connection_type.value,
                    "gateway_provider": record.gateway_provider,
                    "transport": record.transport,
                    "auth_ref": record.auth_ref,
                    "status": record.status,
                    "account_metadata": json.dumps(record.account_metadata),
                    "created_at": record.created_at,
                    "last_verified_at": record.last_verified_at,
                    "last_sync_at": record.last_sync_at,
                },
            )
        stored = await self.get_connection(record.user_id, record.plugin_id)
        assert stored is not None
        return stored

    async def append_raw_records(self, rows: list[RawSourceRecord]) -> list[RawSourceRecord]:
        inserted: list[RawSourceRecord] = []
        async with transaction(self._engine) as connection:
            for row in rows:
                result = await connection.execute(
                    text("""
                    insert into raw_source_events (
                      id, user_id, source_type, external_event_id, content_fingerprint,
                      observed_at, raw_payload_ref, raw_payload_json, plugin_connection_id,
                      sync_run_id, payload_hash, tool_identity, retrieved_at, goal_sync_job_id
                    ) values (
                      :id, :user_id, :source_type, :external_event_id, :fingerprint,
                      :observed_at, :payload_ref, cast(:payload as jsonb), :plugin_connection_id,
                      :sync_run_id, :payload_hash, :tool_identity, :retrieved_at, :goal_sync_job_id
                    ) on conflict do nothing
                    """),
                    {
                        "id": row.id,
                        "user_id": row.cursor_context.get("user_id"),
                        "source_type": row.cursor_context.get("source_type", "mcp"),
                        "external_event_id": row.external_id,
                        "fingerprint": row.payload_hash,
                        "observed_at": row.retrieved_at,
                        "payload_ref": f"mcp://{row.tool_identity}/{row.external_id}",
                        "payload": json.dumps(row.payload),
                        "plugin_connection_id": row.plugin_connection_id,
                        "sync_run_id": row.sync_run_id,
                        "payload_hash": row.payload_hash,
                        "tool_identity": row.tool_identity,
                        "retrieved_at": row.retrieved_at,
                        "goal_sync_job_id": row.cursor_context.get("goal_sync_job_id"),
                    },
                )
                if result.rowcount:
                    inserted.append(row)
        return inserted

    async def list_job_raw_records(
        self, owner_id: UUID, job_ids: list[UUID]
    ) -> list[RawSourceRecord]:
        if not job_ids:
            return []
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text("""
                    select id, plugin_connection_id, external_event_id, tool_identity,
                           retrieved_at, raw_payload_json, payload_hash, sync_run_id,
                           source_type, goal_sync_job_id
                    from raw_source_events
                    where user_id = :owner_id and goal_sync_job_id = any(:job_ids)
                    order by ingested_at, id
                    """),
                    {"owner_id": owner_id, "job_ids": job_ids},
                )
            ).mappings().all()
        return [
            RawSourceRecord(
                id=row["id"],
                plugin_connection_id=row["plugin_connection_id"],
                external_id=row["external_event_id"],
                tool_identity=row["tool_identity"],
                retrieved_at=row["retrieved_at"],
                payload=row["raw_payload_json"],
                payload_hash=row["payload_hash"],
                sync_run_id=row["sync_run_id"],
                cursor_context={
                    "user_id": str(owner_id),
                    "source_type": row["source_type"],
                    "goal_sync_job_id": str(row["goal_sync_job_id"]),
                },
            )
            for row in rows
        ]

    async def save_goal_recipe(self, recipe: GoalSyncRecipeRecord) -> GoalSyncRecipeRecord:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into goal_sync_recipes (
                  goal_id, plugin_id, plugin_connection_id, label, steps_json, approved,
                  schema_version, provenance_json, status, last_successful_sync_at, user_approved_at
                ) values (
                  :goal_id, :plugin_id, :plugin_connection_id, :label, cast(:steps as jsonb), :approved,
                  :schema_version, cast(:provenance as jsonb), :status, :last_successful_sync_at, :user_approved_at
                ) on conflict (goal_id, plugin_id) do update set
                  plugin_connection_id = excluded.plugin_connection_id,
                  label = excluded.label,
                  steps_json = excluded.steps_json,
                  approved = excluded.approved,
                  schema_version = excluded.schema_version,
                  provenance_json = excluded.provenance_json,
                  status = excluded.status,
                  last_successful_sync_at = excluded.last_successful_sync_at,
                  user_approved_at = excluded.user_approved_at,
                  updated_at = now()
                """),
                {
                    "goal_id": recipe.goal_id,
                    "plugin_id": recipe.plugin_id,
                    "plugin_connection_id": recipe.plugin_connection_id,
                    "label": recipe.label,
                    "steps": json.dumps([step.model_dump(mode="json") for step in recipe.steps]),
                    "approved": recipe.approved,
                    "schema_version": recipe.schema_version,
                    "provenance": json.dumps(recipe.provenance),
                    "status": recipe.status,
                    "last_successful_sync_at": recipe.last_successful_sync_at,
                    "user_approved_at": recipe.user_approved_at,
                },
            )
        return recipe

    async def list_goal_recipes(self, goal_id: UUID) -> list[GoalSyncRecipeRecord]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text("select * from goal_sync_recipes where goal_id = :goal_id order by updated_at desc"),
                    {"goal_id": goal_id},
                )
            ).mappings()
        recipes: list[GoalSyncRecipeRecord] = []
        for row in rows:
            steps = [SyncRecipeStep.model_validate(item) for item in row["steps_json"]]
            recipes.append(
                GoalSyncRecipeRecord(
                    goal_id=row["goal_id"],
                    plugin_connection_id=row["plugin_connection_id"],
                    plugin_id=row["plugin_id"],
                    label=row["label"],
                    steps=steps,
                    approved=row["approved"],
                    schema_version=row["schema_version"],
                    provenance=row["provenance_json"] or {},
                    status=row["status"],
                    last_successful_sync_at=row["last_successful_sync_at"],
                    user_approved_at=row["user_approved_at"],
                )
            )
        return recipes

    async def get_goal_recipe(self, goal_id: UUID, plugin_id: str) -> GoalSyncRecipeRecord | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from goal_sync_recipes where goal_id = :goal_id and plugin_id = :plugin_id"
                        ),
                        {"goal_id": goal_id, "plugin_id": plugin_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        steps = [SyncRecipeStep.model_validate(item) for item in row["steps_json"]]
        return GoalSyncRecipeRecord(
            goal_id=row["goal_id"],
            plugin_connection_id=row["plugin_connection_id"],
            plugin_id=row["plugin_id"],
            label=row["label"],
            steps=steps,
            approved=row["approved"],
            schema_version=row["schema_version"],
            provenance=row["provenance_json"] or {},
            status=row["status"],
            last_successful_sync_at=row["last_successful_sync_at"],
            user_approved_at=row["user_approved_at"],
        )


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
