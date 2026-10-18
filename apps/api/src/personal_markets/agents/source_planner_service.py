from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.completion import complete_validated
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.agents.state import redact, stable_run_id
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.integrations.gateway import UnifiedIntegrationGateway
from personal_markets.integrations.mcp_domain import GoalSyncRecipeRecord, ReadCapabilityRecord, SyncRecipeStep
from personal_markets.integrations.plugins import PLUGIN_DEFINITIONS, PluginStatus
from personal_markets.integrations.resource_ranker import rank_resources
from personal_markets.ports import (
    InferenceProvider,
    InferenceRequest,
    SourcePlannerProposal,
    SourceRecommendation,
    SourceResourceSelection,
)


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
        catalog = []
        available_resources: list[dict[str, object]] = []
        for view in plugin_views:
            capabilities = view.definition.capabilities
            if view.connection.status == PluginStatus.CONNECTED:
                discovered = await self._gateway.list_capabilities(view.definition.id)
                capabilities = [
                    {
                        "capability_id": item.get("capability_id"),
                        "label": item.get("label"),
                        "operation": item.get("operation"),
                        "tool_name": item.get("tool_name"),
                    }
                    for item in discovered
                ]
                try:
                    resources = await self._gateway.list_resources(view.definition.id)
                except Exception:
                    resources = []
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
                    "capabilities": capabilities,
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
            self._inference, request, SourcePlannerProposal,
            timeout_seconds=self._settings.inference_run_timeout_seconds,
        )
        proposal = self._validate_plan(proposal)
        proposal = self._attach_ranked_resources(proposal, available_resources, goal.model_dump(mode="json"))
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
        steps: list[SyncRecipeStep] | None = None,
        approved: bool = True,
        activity_types: list[str] | None = None,
    ) -> GoalSyncRecipeRecord:
        goal = await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)
        owner = self._owner_id or getattr(self._gateway, "_user_id", None)
        connection = await self._repository.get_connection(owner, plugin_id)  # type: ignore[attr-defined]
        if connection is None:
            raise KeyError(f"plugin {plugin_id} is not connected")
        recipe_steps = steps or await self.build_recipe_steps(
            plugin_id,
            resource_ids or [],
            label,
            connection.id,
            activity_types=activity_types,
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
            provenance={"approved_via": "goal_evidence_workspace"},
        )
        return await self._repository.save_goal_recipe(recipe)  # type: ignore[attr-defined]

    async def build_recipe_steps(
        self,
        plugin_id: str,
        resource_ids: list[str],
        label: str,
        connection_id: UUID,
        activity_types: list[str] | None = None,
    ) -> list[SyncRecipeStep]:
        capabilities: list[ReadCapabilityRecord] = await self._repository.list_capabilities(connection_id)  # type: ignore[attr-defined]
        selected = _select_capabilities(capabilities, activity_types)
        if not selected:
            return [
                SyncRecipeStep(
                    capability_id=f"{plugin_id}.selected.read",
                    arguments={"label": label, "resource_ids": resource_ids},
                )
            ]
        targets = resource_ids or [label]
        steps: list[SyncRecipeStep] = []
        for capability in selected:
            for target in targets:
                steps.append(
                    SyncRecipeStep(
                        capability_id=capability.capability_id,
                        tool_name=capability.tool_name,
                        resource_uri=f"composio://{plugin_id}/{target}",
                        arguments=_arguments_for_resource(target, label, capability),
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
                            "recommended": item.recommended or item.goal_relevance in {"high", "medium"},
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
            irrelevant.append(rec.model_copy(update={"resources": resources}))
        for plugin_id, resources in by_plugin.items():
            if plugin_id in seen:
                continue
            if any(item.recommended for item in resources):
                recommended.append(
                    SourceRecommendation(
                        plugin_id=plugin_id,
                        relevance="recommended",
                        rationale="Discovered resources overlap the goal contract.",
                        resources=resources,
                    )
                )
            else:
                irrelevant.append(
                    SourceRecommendation(
                        plugin_id=plugin_id,
                        relevance="irrelevant",
                        rationale="Discovered resources do not overlap the goal contract.",
                        resources=resources,
                    )
                )
        return proposal.model_copy(update={"recommended": recommended, "irrelevant": irrelevant})


def _select_capabilities(
    capabilities: list[ReadCapabilityRecord],
    activity_types: list[str] | None,
) -> list[ReadCapabilityRecord]:
    if not capabilities:
        return []
    if activity_types:
        wanted = {item.lower() for item in activity_types}
        matched = [
            cap
            for cap in capabilities
            if any(token in (cap.tool_name or cap.label or "").lower() for token in wanted)
        ]
        if matched:
            return matched
    return [
        min(
            capabilities,
            key=lambda cap: (0 if (cap.tool_name or "").lower().startswith("list") else 1, cap.label),
        )
    ]


def _arguments_for_resource(target: str, label: str, capability: ReadCapabilityRecord) -> dict[str, object]:
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
