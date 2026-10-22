from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.behavior.commitments import (
    Commitment,
    CommitmentObservation,
    OutcomeStatus,
    get_commitment_store,
    trials_from_commitments,
)
from personal_markets.behavior.service import BehaviorService
from personal_markets.core.errors import ResourceNotFoundError, SemanticProviderError
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.integrations.goal_sync_jobs import GoalSyncJob, get_goal_sync_job_store
from personal_markets.integrations.source_watches import SourceWatch, get_source_watch_store
from personal_markets.ports import SourcePlannerProposal
from personal_markets.wiring import (
    get_evidence_service,
    get_goal_service,
    get_integration_repository,
    get_source_planner_service,
)

router = APIRouter(prefix="/api/v1/goals", tags=["evidence-sources"])


class SaveRecipeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    resource_ids: list[str] = Field(default_factory=list)
    approved: bool = True
    activity_types: list[str] = Field(default_factory=list)


class SaveWatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    scope: Literal["resource", "parent"] = "resource"
    interval_minutes: int = Field(default=60, ge=15, le=10080)


class WatchStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class CreateCommitmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=160)
    planned_quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    window_start: datetime
    window_end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> CreateCommitmentBody:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("Commitment windows need a timezone")
        if self.window_end <= self.window_start:
            raise ValueError("Commitment window must end after it starts")
        return self


class ObserveCommitmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OutcomeStatus
    actual_quantity: float | None = Field(default=None, ge=0)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_observation(self) -> ObserveCommitmentBody:
        if self.observed_at.tzinfo is None:
            raise ValueError("Observation timestamp needs a timezone")
        if self.status in {"completed", "partial"} and self.actual_quantity is None:
            raise ValueError("An observed quantity is required")
        return self


@router.get("/{goal_id}/commitments")
async def list_commitments(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, list[Commitment] | list[CommitmentObservation]]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    plans, observations = await get_commitment_store().list_for_goals(principal.user_id, [goal_id])
    return {"commitments": plans, "observations": observations}


@router.post("/{goal_id}/commitments", response_model=Commitment)
async def create_commitment(
    goal_id: UUID,
    body: CreateCommitmentBody,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> Commitment:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    plan = Commitment(owner_id=principal.user_id, goal_id=goal_id, **body.model_dump())
    return await get_commitment_store().create(plan)


@router.post(
    "/{goal_id}/commitments/{commitment_id}/observations", response_model=CommitmentObservation
)
async def observe_commitment(
    goal_id: UUID,
    commitment_id: UUID,
    body: ObserveCommitmentBody,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> CommitmentObservation:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    plans, _ = await get_commitment_store().list_for_goals(principal.user_id, [goal_id])
    if not any(plan.id == commitment_id for plan in plans):
        raise ResourceNotFoundError("Commitment not found")
    return await get_commitment_store().observe(
        principal.user_id, commitment_id, **body.model_dump()
    )


@router.get("/{goal_id}/evidence/sources/plan", response_model=SourcePlannerProposal)
async def evidence_source_plan(
    goal_id: UUID,
    planner: Annotated[SourcePlannerService, Depends(get_source_planner_service)],
) -> SourcePlannerProposal:
    return await planner.plan(str(goal_id))


@router.get("/{goal_id}/evidence/sources/recipes")
async def list_goal_recipes(
    goal_id: UUID,
    planner: Annotated[SourcePlannerService, Depends(get_source_planner_service)],
) -> list[dict[str, object]]:
    recipes = await planner.list_recipes(str(goal_id))
    return [item.model_dump(mode="json") for item in recipes]


@router.get("/{goal_id}/evidence/sources/watches", response_model=list[SourceWatch])
async def list_source_watches(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> list[SourceWatch]:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    return await get_source_watch_store().list_for_goal(principal.user_id, goal_id)


@router.post("/{goal_id}/evidence/sources/watches", response_model=SourceWatch)
async def save_source_watch(
    goal_id: UUID,
    body: SaveWatchBody,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> SourceWatch:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    repo = get_integration_repository()
    recipe = await repo.get_goal_recipe(goal_id, body.plugin_id)
    connection = await repo.get_connection(principal.user_id, body.plugin_id)
    if (
        not recipe
        or not recipe.approved
        or not connection
        or connection.status != "connected"
        or recipe.plugin_connection_id != connection.id
    ):
        raise SemanticProviderError("Approve this connected source before enabling monitoring.")
    expected_uri = f"composio://{body.plugin_id}/{body.resource_id}"
    if not any(step.resource_uri == expected_uri for step in recipe.steps):
        raise SemanticProviderError(
            "Select an approved source resource before enabling monitoring."
        )
    if body.scope == "parent":
        if body.plugin_id != "notion":
            raise SemanticProviderError("Parent monitoring is available for Notion pages.")
        try:
            UUID(body.resource_id)
        except ValueError as error:
            raise SemanticProviderError("Select a valid Notion parent page.") from error
        capabilities = await repo.list_capabilities(connection.id)
        if not any(
            item.approved and item.tool_name == "NOTION_FETCH_BLOCK_CONTENTS"
            for item in capabilities
        ):
            raise SemanticProviderError(
                "This Notion connection cannot discover pages inside the selected area."
            )
    return await get_source_watch_store().save(
        SourceWatch(
            owner_id=principal.user_id,
            goal_id=goal_id,
            plugin_connection_id=connection.id,
            plugin_id=body.plugin_id,
            resource_id=body.resource_id,
            scope=body.scope,
            interval_minutes=body.interval_minutes,
        )
    )


@router.patch("/{goal_id}/evidence/sources/watches/{watch_id}", response_model=SourceWatch)
async def update_source_watch(
    goal_id: UUID,
    watch_id: UUID,
    body: WatchStatusBody,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> SourceWatch:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    if body.status not in {"active", "paused", "revoked"}:
        raise SemanticProviderError("Choose active, paused, or revoked.")
    watch = await get_source_watch_store().set_status(
        principal.user_id, goal_id, watch_id, body.status
    )
    if watch is None:
        raise ResourceNotFoundError("Source watch not found")
    return watch


@router.post("/{goal_id}/evidence/sources/{plugin_id}/recipe")
async def save_goal_recipe(
    goal_id: UUID,
    plugin_id: str,
    body: SaveRecipeBody,
    planner: Annotated[SourcePlannerService, Depends(get_source_planner_service)],
) -> dict[str, object]:
    recipe = await planner.save_recipe(
        str(goal_id),
        plugin_id,
        label=body.label,
        resource_ids=body.resource_ids,
        approved=body.approved,
        activity_types=body.activity_types or None,
    )
    return recipe.model_dump(mode="json")


@router.get("/{goal_id}/behavior-profile")
async def behavior_profile(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, object]:
    goal = await goals.get_goal_by_string(str(goal_id), owner_id=principal.user_id)
    events = await evidence.list_for_goal(goal.goal_id)
    plans, observations = await get_commitment_store().list_for_goals(
        principal.user_id, [goal.goal_id]
    )
    profile = BehaviorService().profile_from_evidence(
        events, goal, commitment_trials=trials_from_commitments(plans, observations)
    )
    return profile.model_dump(mode="json")


@router.post("/{goal_id}/evidence/sources/sync", status_code=202, response_model=GoalSyncJob)
async def sync_goal_sources(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> GoalSyncJob:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    return await get_goal_sync_job_store().enqueue(principal.user_id, goal_id)


@router.get("/{goal_id}/evidence/sources/sync", response_model=GoalSyncJob | None)
async def latest_goal_sync(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> GoalSyncJob | None:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    return await get_goal_sync_job_store().latest(principal.user_id, goal_id)


@router.get("/{goal_id}/evidence/sources/sync/{run_id}", response_model=GoalSyncJob)
async def goal_sync_status(
    goal_id: UUID,
    run_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> GoalSyncJob:
    await goals.get_goal(goal_id, owner_id=principal.user_id)
    job = await get_goal_sync_job_store().get(principal.user_id, goal_id, run_id)
    if job is None:
        raise ResourceNotFoundError("Source sync not found")
    return job
