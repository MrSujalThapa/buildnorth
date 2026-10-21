from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import structlog

from personal_markets.core.errors import SemanticProviderError
from personal_markets.integrations.mcp_domain import RawSourceRecord
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
            approved = [
                item.model_copy(
                    update={
                        "steps": [
                            step
                            for step in item.steps
                            if step.resource_uri in self._watch_resource_uris
                        ]
                    }
                )
                for item in approved
            ]
            approved = [item for item in approved if item.steps]
        if not approved:
            return {"status": "no_recipes", "message": "No approved goal-specific sync recipes."}

        for recipe in approved:
            if not recipe.steps or not all(
                _supported_goal_step(recipe.plugin_id, step.tool_name) for step in recipe.steps
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
    if not tool_name:
        return False
    if plugin_id == "notion":
        return tool_name in {
            "NOTION_GET_PAGE_MARKDOWN",
            "NOTION_FETCH_ALL_BLOCK_CONTENTS",
            "NOTION_FETCH_BLOCK_CONTENTS",
        }
    if plugin_id == "github":
        return tool_name in {
            "GITHUB_LIST_COMMITS",
            "GITHUB_GET_PULL_REQUESTS",
            "GITHUB_LIST_PULL_REQUESTS",
            "GITHUB_LIST_ISSUES_FOR_A_REPOSITORY",
            "GITHUB_LIST_REPOSITORY_ISSUES",
        }
    return True
