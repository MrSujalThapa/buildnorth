from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from personal_markets.agents.completion import complete_validated
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.agents.state import redact, stable_run_id
from personal_markets.core.config import Settings
from personal_markets.core.errors import IntegrationProviderError, SemanticProviderError
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.integrations.gateway import UnifiedIntegrationGateway
from personal_markets.integrations.generic_reads import (
    arguments_for_selection,
    bound_page_arguments,
)
from personal_markets.integrations.mcp_domain import (
    GoalSyncRecipeRecord,
    MCPToolDescriptor,
    ReadCapabilityRecord,
    SyncRecipeStep,
)
from personal_markets.integrations.plugins import PLUGIN_DEFINITIONS, PluginStatus
from personal_markets.integrations.provider_contract import required_argument_names
from personal_markets.integrations.resource_ranker import rank_resources
from personal_markets.ports import (
    InferenceProvider,
    InferenceRequest,
    SourcePlannerProposal,
    SourceRecommendation,
    SourceResourceSelection,
)

logger = logging.getLogger(__name__)


class SourcePlannerService:
    def __init__(
        self,
        settings: Settings,
        inference: InferenceProvider,
        goals: GoalService,
        evidence: EvidenceService,
        gateway: UnifiedIntegrationGateway,
        run_store: object,
        repository: object,
        owner_id: UUID | None = None,
    ) -> None:
        self._settings = settings
        self._inference = inference
        self._goals = goals
        self._evidence = evidence
        self._gateway = gateway
        self._run_store = run_store
        self._repository = repository
        self._owner_id = owner_id
        self._ladders = ladders(settings)

    async def plan(self, goal_id: str) -> SourcePlannerProposal:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        evidence = await self._evidence.list_for_goal(goal.goal_id)
        plugin_views = await self._gateway.views()
        semaphore = asyncio.Semaphore(4)

        async def load_connected(
            plugin_id: str,
        ) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, str] | None]:
            async with semaphore:

                async def resources_or_empty() -> tuple[
                    list[dict[str, object]], dict[str, str] | None
                ]:
                    try:
                        return await self._gateway.list_resources(plugin_id), None
                    except IntegrationProviderError as error:
                        return [], {
                            "plugin_id": plugin_id,
                            "kind": error.kind,
                            "message": str(error),
                        }
                    except Exception:
                        logger.warning(
                            "source_resource_discovery_failed plugin_id=%s error_type=%s",
                            plugin_id,
                            "Exception",
                        )
                        return [], {
                            "plugin_id": plugin_id,
                            "kind": "temporary_upstream_failure",
                            "message": "Resource discovery failed.",
                        }

                resources, issue = await resources_or_empty()
                capabilities = await self._gateway.list_capabilities(plugin_id)
                return capabilities, resources, issue

        connected_ids = [
            view.definition.id
            for view in plugin_views
            if view.connection.status == PluginStatus.CONNECTED
        ]
        discovery_issues: list[dict[str, str]] = []
        connected_results = dict(
            zip(
                connected_ids,
                await asyncio.gather(*(load_connected(plugin_id) for plugin_id in connected_ids)),
                strict=True,
            )
        )
        catalog = []
        available_resources: list[dict[str, object]] = []
        for view in plugin_views:
            reported_capabilities: object = view.definition.capabilities
            if view.connection.status == PluginStatus.CONNECTED:
                discovered, resources, issue = connected_results[view.definition.id]
                if issue is not None:
                    discovery_issues.append(issue)
                reported_capabilities = [
                    {
                        "capability_id": item.get("capability_id"),
                        "label": item.get("label"),
                        "operation": item.get("operation"),
                        "tool_name": item.get("tool_name"),
                    }
                    for item in discovered
                ]
                for item in resources:
                    label = str(item.get("name") or item.get("uri") or "")
                    if "default scope" in label.lower():
                        continue
                    available_resources.append(
                        {
                            "plugin_id": view.definition.id,
                            "resource_id": str(item.get("uri") or item.get("name") or ""),
                            "id": str(item.get("uri") or item.get("name") or ""),
                            "label": label,
                            "description": str(item.get("description") or ""),
                            "resource_type": str(item.get("resource_type") or "resource"),
                            "name": str(item.get("name") or ""),
                        }
                    )
            catalog.append(
                {
                    "plugin_id": view.definition.id,
                    "name": view.definition.name,
                    "description": view.definition.description,
                    "used_for": view.definition.used_for,
                    "capabilities": reported_capabilities,
                    "connection_status": view.connection.status.value,
                }
            )
        seen = {str(item["plugin_id"]) for item in catalog}
        for definition in PLUGIN_DEFINITIONS:
            if definition.id in seen:
                continue
            catalog.append(
                {
                    "plugin_id": definition.id,
                    "name": definition.name,
                    "description": definition.description,
                    "used_for": definition.used_for,
                    "capabilities": definition.capabilities,
                    "connection_status": "not_connected",
                }
            )
        goal_payload = goal.model_dump(mode="json")
        if connected_ids:
            # Rank only resources discovered within the authorized connection.
            # A weak title match is not evidence, and does not justify a paid
            # inference request just to display source choices.
            return self._attach_ranked_resources(
                SourcePlannerProposal(
                    goal_title=goal.title,
                    goal_type=str(goal.goal_type),
                    state_dimensions=goal.state_dimensions,
                    discovery_issues=discovery_issues,
                ),
                available_resources,
                goal_payload,
            )
        thread_id = str(uuid4())
        payload = {
            "goal": goal.model_dump(mode="json"),
            "state_dimensions": goal.state_dimensions,
            "evidence_summary": [item.summary for item in evidence[:12]],
            "plugins": catalog,
            "available_resources": available_resources,
        }
        prompt = load_prompt("source_planner")
        ladder = self._ladders["source_planner"]
        run_id = stable_run_id(thread_id, "source_planner", 0)
        request = InferenceRequest(
            instructions=prompt.text,
            input=redact(payload),
            output_schema=strict_json_schema(SourcePlannerProposal),
            model=None,
            fallback_models=[],
            pool=ladder.pool,  # type: ignore[arg-type]
            agent_name="research",
            user_id=self._owner_id,
        )
        proposal, response = await complete_validated(
            self._inference,
            request,
            SourcePlannerProposal,
            timeout_seconds=self._settings.inference_run_timeout_seconds,
        )
        proposal = self._validate_plan(proposal)
        proposal = self._attach_ranked_resources(
            proposal, available_resources, goal.model_dump(mode="json")
        )
        if discovery_issues:
            proposal = proposal.model_copy(update={"discovery_issues": discovery_issues})
        await self._run_store.record(  # type: ignore[attr-defined]
            {
                "id": run_id,
                "thread_id": thread_id,
                "agent_type": "research",
                "agent_version": prompt.version,
                "model_provider": response.provider,
                "model_name": response.model,
                "prompt_version": prompt.version,
                "prompt_checksum": prompt.checksum,
                "input_refs": list(payload.keys()),
                "output": proposal.model_dump(mode="json"),
                "validation_status": "ok",
                "retry_count": response.retries,
                "duration_ms": response.latency_ms,
                "token_usage": response.usage,
                "estimated_cost": estimate_cost_usd(
                    response.model,
                    int(response.usage.get("input_tokens", 0)),
                    int(response.usage.get("output_tokens", 0)),
                ),
                "tool_trace": [{"tool": "source_planning", "goal_id": goal_id}],
                "status": "completed",
            }
        )
        return proposal

    async def save_recipe(
        self,
        goal_id: str,
        plugin_id: str,
        *,
        label: str,
        resource_ids: list[str] | None = None,
        approved: bool = True,
        activity_types: list[str] | None = None,
        read_arguments: dict[str, Any] | None = None,
    ) -> GoalSyncRecipeRecord:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        owner = self._owner_id or getattr(self._gateway, "_user_id", None)
        connection = await self._repository.get_connection(owner, plugin_id)  # type: ignore[attr-defined]
        if connection is None:
            raise KeyError(f"plugin {plugin_id} is not connected")
        recipe_steps = await self.build_recipe_steps(
            plugin_id,
            resource_ids or [],
            label,
            connection.id,
            activity_types=activity_types,
            read_arguments=read_arguments,
        )
        now = datetime.now(UTC)
        recipe = GoalSyncRecipeRecord(
            goal_id=goal.goal_id,
            plugin_connection_id=connection.id,
            plugin_id=plugin_id,
            label=label,
            steps=recipe_steps,
            approved=approved,
            user_approved_at=now if approved else None,
            provenance={
                "approved_via": "goal_evidence_workspace",
                "connected_account_id": connection.account_metadata.get("connected_account_id", ""),
            },
        )
        return await self._repository.save_goal_recipe(recipe)  # type: ignore[attr-defined]

    async def build_recipe_steps(
        self,
        plugin_id: str,
        resource_ids: list[str],
        label: str,
        connection_id: UUID,
        activity_types: list[str] | None = None,
        read_arguments: dict[str, Any] | None = None,
    ) -> list[SyncRecipeStep]:
        if not resource_ids:
            raise SemanticProviderError(
                "Choose an accessible resource or bounded query before saving this source."
            )
        capabilities: list[ReadCapabilityRecord] = await self._repository.list_capabilities(  # type: ignore[attr-defined]
            connection_id
        )
        selected = _select_capabilities(capabilities, activity_types, plugin_id=plugin_id)
        if activity_types and not selected:
            raise SemanticProviderError("No supported read action matches the selected activity.")
        if not selected:
            raise SemanticProviderError(
                "This connection has no supported read action. Reconnect it and try again."
            )
        targets = resource_ids or [label]
        steps: list[SyncRecipeStep] = []
        for capability in selected:
            for target in targets:
                arguments = _arguments_for_resource(target, label, capability)
                if plugin_id not in {"github", "notion", "calendar"}:
                    tool = MCPToolDescriptor(
                        name=capability.tool_name or "", input_schema=capability.input_schema
                    )
                    generic_arguments = arguments_for_selection(tool, target, read_arguments)
                    if generic_arguments is None:
                        raise SemanticProviderError(
                            "This read cannot be scoped safely to the selected resource or query."
                        )
                    arguments = bound_page_arguments(tool, generic_arguments)
                    from jsonschema import Draft202012Validator, SchemaError, ValidationError

                    body = capability.input_schema.get("parameters", capability.input_schema)
                    try:
                        Draft202012Validator.check_schema(body)
                        Draft202012Validator(body).validate(arguments)
                    except (SchemaError, ValidationError) as error:
                        raise SemanticProviderError(
                            "The selected values do not match this read action's schema."
                        ) from error
                missing = [
                    name
                    for name in required_argument_names(capability.input_schema)
                    if name not in arguments or arguments[name] in ("", None)
                ]
                if missing:
                    raise SemanticProviderError(
                        "The provider tool schema requires arguments this source cannot fill. "
                        "Select the source again."
                    )
                steps.append(
                    SyncRecipeStep(
                        capability_id=capability.capability_id,
                        tool_name=capability.tool_name,
                        resource_uri=f"composio://{plugin_id}/{target}",
                        arguments=arguments,
                    )
                )
        return steps

    async def list_recipes(self, goal_id: str) -> list[GoalSyncRecipeRecord]:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        return await self._repository.list_goal_recipes(goal.goal_id)  # type: ignore[attr-defined]

    @staticmethod
    def _validate_plan(proposal: SourcePlannerProposal) -> SourcePlannerProposal:
        recommended = [item for item in proposal.recommended if item.relevance != "irrelevant"]
        irrelevant = list(proposal.irrelevant)
        return proposal.model_copy(update={"recommended": recommended, "irrelevant": irrelevant})

    @staticmethod
    def _attach_ranked_resources(
        proposal: SourcePlannerProposal,
        available: list[dict[str, object]],
        goal: dict[str, object],
    ) -> SourcePlannerProposal:
        if not available:
            enriched = []
            for rec in proposal.recommended:
                resources = [
                    item.model_copy(
                        update={
                            "why": item.why or item.rationale,
                            "recommended": item.recommended
                            or item.goal_relevance in {"high", "medium"},
                        }
                    )
                    for item in rec.resources
                ]
                enriched.append(rec.model_copy(update={"resources": resources}))
            return proposal.model_copy(update={"recommended": enriched})

        ranked = rank_resources(available, goal)
        by_plugin: dict[str, list[SourceResourceSelection]] = {}
        for item in ranked:
            plugin_id = str(item.get("plugin_id") or "")
            by_plugin.setdefault(plugin_id, []).append(
                SourceResourceSelection(
                    resource_id=str(item["resource_id"]).replace(f"composio://{plugin_id}/", ""),
                    label=str(item["label"]),
                    rationale=str(item["rationale"]),
                    resource_type=str(item["resource_type"]),
                    why=str(item["why"]),
                    goal_relevance=str(item["goal_relevance"]),
                    state_variables=list(item["state_variables"]),
                    recommended=bool(item["recommended"]),
                )
            )
        recommended: list[SourceRecommendation] = []
        irrelevant: list[SourceRecommendation] = []
        seen: set[str] = set()
        for rec in proposal.recommended:
            seen.add(rec.plugin_id)
            resources = by_plugin.get(rec.plugin_id) or rec.resources
            recommended.append(rec.model_copy(update={"resources": resources}))
        for rec in proposal.irrelevant:
            seen.add(rec.plugin_id)
            resources = by_plugin.get(rec.plugin_id) or rec.resources
            if any(item.recommended for item in resources):
                recommended.append(
                    rec.model_copy(
                        update={
                            "relevance": "recommended",
                            "rationale": "An accessible page may relate to this goal.",
                            "resources": resources,
                        }
                    )
                )
            else:
                irrelevant.append(rec.model_copy(update={"resources": resources}))
        for plugin_id, resources in by_plugin.items():
            if plugin_id in seen:
                continue
            if any(item.recommended for item in resources):
                recommended.append(
                    SourceRecommendation(
                        plugin_id=plugin_id,
                        relevance="recommended",
                        rationale="These accessible sources may relate to this goal.",
                        resources=resources,
                    )
                )
            else:
                irrelevant.append(
                    SourceRecommendation(
                        plugin_id=plugin_id,
                        relevance="irrelevant",
                        rationale="No clear match among accessible sources.",
                        resources=resources,
                    )
                )
        return proposal.model_copy(update={"recommended": recommended, "irrelevant": irrelevant})


def _select_capabilities(
    capabilities: list[ReadCapabilityRecord],
    activity_types: list[str] | None,
    *,
    plugin_id: str | None = None,
) -> list[ReadCapabilityRecord]:
    from personal_markets.integrations.provider_contract import adapter_for_tool_names

    capabilities = [
        cap
        for cap in capabilities
        if cap.approved and (cap.operation == "read" or cap.operation.endswith(".read"))
    ]
    if not capabilities:
        return []
    names = [cap.tool_name or "" for cap in capabilities]
    if plugin_id is None:
        from personal_markets.integrations.provider_contract import adapter_for_tool_names

        plugin_id = adapter_for_tool_names(names).plugin_id
    if plugin_id not in {"github", "notion", "calendar"}:
        from personal_markets.integrations.generic_reads import goal_read_tools

        available = goal_read_tools(
            plugin_id,
            [
                MCPToolDescriptor(name=cap.tool_name or "", input_schema=cap.input_schema)
                for cap in capabilities
                if cap.tool_name
            ],
        )
        selected_names: list[str] | None = [
            name for name in (activity_types or []) if name in {tool.name for tool in available}
        ]
        if selected_names is None or len(selected_names) != 1:
            return []
    else:
        selected_names = adapter_for_tool_names(names).select_tool_names(
            [name for name in names if name],
            activity_types,
        )
    if not selected_names:
        return []
    chosen: list[ReadCapabilityRecord] = []
    for tool_name in selected_names:
        match = next((cap for cap in capabilities if cap.tool_name == tool_name), None)
        if match is not None:
            chosen.append(match)
    return chosen if len(chosen) == len(selected_names) else []


def _arguments_for_resource(
    target: str, label: str, capability: ReadCapabilityRecord
) -> dict[str, object]:
    schema = capability.input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    arguments: dict[str, object] = {"resource_id": target, "label": label}
    cleaned = target.replace("composio://", "")
    if "/" in cleaned and "owner" in properties and "repo" in properties:
        owner, repo = cleaned.split("/", 1)
        if ":" in owner:
            owner = owner.split(":")[-1]
        arguments["owner"] = owner
        arguments["repo"] = repo.split("@")[0]
        if "@" in repo and "sha" in properties:
            arguments["sha"] = repo.split("@", 1)[1]
        return arguments
    for key in (
        "spreadsheet_id",
        "spreadsheetId",
        "page_id",
        "block_id",
        "database_id",
        "calendar_id",
        "calendarId",
        "file_id",
        "folder_id",
        "q",
        "query",
        "label",
        "range",
    ):
        if key in properties:
            arguments[key] = target
            break
    return arguments
