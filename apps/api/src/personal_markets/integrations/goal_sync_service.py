from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import structlog

from personal_markets.core.errors import SemanticProviderError
from personal_markets.integrations.mcp_domain import RawSourceRecord
from personal_markets.integrations.provider_contract import get_adapter
from personal_markets.integrations.source_watches import get_source_watch_store
from personal_markets.ports import WorkflowRequest


class GoalSyncService:
    def __init__(
        self,
        settings,
        gateway,
        repository,
        goals,
        workflow,
        evidence,
        owner_id=None,
        job_id: UUID | None = None,
        replay_job_ids: list[UUID] | None = None,
        watch_resource_uris: list[str] | None = None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._repository = repository
        self._goals = goals
        self._workflow = workflow
        self._evidence = evidence
        self._owner_id = owner_id
        self._job_id = job_id
        self._replay_job_ids = replay_job_ids or []
        self._watch_resource_uris = (
            set(watch_resource_uris) if watch_resource_uris is not None else None
        )

    async def sync_goal_sources(
        self,
        goal_id: str,
        *,
        on_stage: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ):
        started = time.perf_counter()
        log = structlog.get_logger(__name__)
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        recipes = await self._repository.list_goal_recipes(goal.goal_id)
        approved = [item for item in recipes if item.approved]
        if self._watch_resource_uris is not None:
            watch_store = get_source_watch_store()
            watches = await watch_store.list_for_goal(
                self._owner_id, goal.goal_id
            )
            active_watches = [
                watch for watch in watches
                if watch.status == "active"
                and f"composio://{watch.plugin_id}/{watch.resource_id}"
                in self._watch_resource_uris
            ]
            allowed = {
                (watch.plugin_connection_id, f"composio://{watch.plugin_id}/{watch.resource_id}")
                for watch in active_watches
            }
            approved = [
                item.model_copy(
                    update={
                        "steps": [
                            step
                            for step in item.steps
                            if (item.plugin_connection_id, step.resource_uri) in allowed
                        ]
                    }
                )
                for item in approved
            ]
            approved = [item for item in approved if item.steps]
            parent_ids = {
                (watch.plugin_connection_id, watch.plugin_id, watch.resource_id)
                for watch in active_watches
                if watch.status == "active"
                and watch.scope == "parent"
                and get_adapter(watch.plugin_id).supports_parent_watch
            }
            if parent_ids:
                expanded = []
                for recipe in approved:
                    steps = list(recipe.steps)
                    if get_adapter(recipe.plugin_id).supports_parent_watch:
                        for step in recipe.steps:
                            parent_id = step.resource_uri.removeprefix(
                                f"composio://{recipe.plugin_id}/"
                            )
                            if (
                                recipe.plugin_connection_id, recipe.plugin_id, parent_id
                            ) not in parent_ids:
                                continue
                            argument_key = next(
                                (key for key in ("block_id", "page_id") if key in step.arguments),
                                None,
                            )
                            if argument_key is None:
                                raise SemanticProviderError(
                                    "This Notion read action cannot monitor child pages."
                                )
                            children = await self._gateway.list_descendants(
                                recipe.plugin_id, parent_id
                            )
                            for child_id in children:
                                steps.append(step.model_copy(update={
                                    "resource_uri": f"composio://{recipe.plugin_id}/{child_id}",
                                    "arguments": {**step.arguments, argument_key: child_id},
                                }))
                    expanded.append(recipe.model_copy(update={"steps": steps}))
                approved = expanded
        if not approved:
            return {"status": "no_recipes", "message": "No approved goal-specific sync recipes."}

        for recipe in approved:
            if self._watch_resource_uris is not None:
                connection = await self._repository.get_connection(
                    self._owner_id, recipe.plugin_id
                )
                if (
                    connection is None
                    or connection.status != "connected"
                    or connection.id != recipe.plugin_connection_id
                ):
                    raise SemanticProviderError(
                        "The watched connection changed or expired. "
                        "Reconnect and approve this source again."
                    )
            if recipe.plugin_id not in {"github", "notion", "calendar"}:
                connection = await self._repository.get_connection(
                    self._owner_id, recipe.plugin_id
                )
                account_id = recipe.provenance.get("connected_account_id")
                if (connection is None or not account_id or
                    account_id != connection.account_metadata.get("connected_account_id")):
                    raise SemanticProviderError(
                        "The connected account changed. Select this source again."
                    )
            if not recipe.steps or not all(
                _supported_goal_step(recipe.plugin_id, step.tool_name)
                or recipe.plugin_id not in {"github", "notion", "calendar"}
                for step in recipe.steps
            ):
                raise SemanticProviderError(
                    f"Select the {recipe.plugin_id} source again to choose a supported activity."
                )

        replay = (
            await self._repository.list_job_raw_records(self._owner_id, self._replay_job_ids)
            if self._replay_job_ids
            else []
        )

        new_records: list[RawSourceRecord] = list(replay)
        replayed_providers = {str(record.cursor_context.get("source_type")) for record in replay}
        scanned = 0
        run_ids: list[str] = []
        for recipe in approved:
            if recipe.plugin_id in replayed_providers:
                continue
            source_started = time.perf_counter()
            sync_kwargs: dict[str, Any] = {"steps": recipe.steps}
            if self._job_id is not None:
                sync_kwargs["goal_sync_job_id"] = self._job_id
            result = await self._gateway.sync(recipe.plugin_id, **sync_kwargs)
            scanned += int(result.get("records_read") or 0)
            if result.get("sync_run_id"):
                run_ids.append(str(result["sync_run_id"]))
            log.info(
                "goal_source_sync_stage",
                goal_id=goal_id,
                provider=recipe.plugin_id,
                sync_run_id=result.get("sync_run_id"),
                duration_ms=round((time.perf_counter() - source_started) * 1000),
                records_read=result.get("records_read", 0),
                records_new=result.get("records_new", 0),
            )
            for row in result.get("new_records") or []:
                if isinstance(row, dict):
                    new_records.append(RawSourceRecord.model_validate(row))
            if on_stage is not None:
                await on_stage(
                    "fetching_sources",
                    {
                        "records_scanned": scanned,
                        "records_added": len(new_records),
                        "sync_run_ids": run_ids,
                    },
                )

        if not new_records:
            return {
                "status": "no_new_records",
                "records_synced": 0,
                "records_scanned": scanned,
                "duplicates": scanned,
                "sync_run_ids": run_ids,
            }

        if replay and on_stage is not None:
            await on_stage(
                "fetching_sources",
                {
                    "records_scanned": len(replay),
                    "records_added": len(replay),
                    "replayed_records": len(replay),
                },
            )

        if on_stage is not None:
            await on_stage(
                "processing_evidence",
                {
                    "records_scanned": scanned,
                    "records_added": len(new_records),
                    "duplicates": max(0, scanned - len(new_records)),
                    "sync_run_ids": run_ids,
                },
            )
        workflow_started = time.perf_counter()
        snapshot = await self._workflow.start(
            WorkflowRequest(
                kind="add_evidence",
                goal_id=goal.goal_id,
                evidence_text=f"Synced {len(new_records)} records from approved integrations.",
                mcp_records=[record.model_dump(mode="json") for record in new_records],
                user_id=self._owner_id,
            )
        )
        log.info(
            "goal_source_sync_workflow",
            goal_id=goal_id,
            duration_ms=round((time.perf_counter() - workflow_started) * 1000),
            total_ms=round((time.perf_counter() - started) * 1000),
            records_new=len(new_records),
            records_scanned=scanned,
            workflow_status=snapshot.status,
        )
        return snapshot


def _supported_goal_step(plugin_id: str, tool_name: str | None) -> bool:
    return get_adapter(plugin_id).is_supported_goal_read(tool_name)
