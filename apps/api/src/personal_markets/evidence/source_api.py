from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.behavior.service import BehaviorService
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.integrations.mcp_domain import SyncRecipeStep
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.ports import SourcePlannerProposal, WorkflowSnapshot
from personal_markets.wiring import (
    get_evidence_service,
    get_goal_service,
    get_goal_sync_service,
    get_source_planner_service,
)

router = APIRouter(prefix="/api/v1/goals", tags=["evidence-sources"])


class SaveRecipeBody(BaseModel):
    label: str = Field(min_length=1)
    resource_ids: list[str] = Field(default_factory=list)
    approved: bool = True
    activity_types: list[str] = Field(default_factory=list)
    steps: list[SyncRecipeStep] | None = None


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
        steps=body.steps,
        approved=body.approved,
        activity_types=body.activity_types or None,
    )
    return recipe.model_dump(mode="json")


@router.get("/{goal_id}/behavior-profile")
async def behavior_profile(
    goal_id: UUID,
    goals: Annotated[GoalService, Depends(get_goal_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> dict[str, object]:
    goal = await goals.get_goal_by_string(str(goal_id))
    events = await evidence.list_for_goal(goal.goal_id)
    profile = BehaviorService().profile_from_evidence(events, goal)
    return profile.model_dump(mode="json")


@router.post("/{goal_id}/evidence/sources/sync")
async def sync_goal_sources(
    goal_id: UUID,
    sync: Annotated[GoalSyncService, Depends(get_goal_sync_service)],
) -> WorkflowSnapshot | dict[str, object]:
    return await sync.sync_goal_sources(str(goal_id))
