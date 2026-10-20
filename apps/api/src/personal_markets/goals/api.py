from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.collections.service import CollectionService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.what_if.service import WhatIfService
from personal_markets.wiring import get_collection_service, get_goal_service, get_what_if_service

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


class ArchiveBody(BaseModel):
    goal_ids: list[UUID] = Field(min_length=1)


@router.get("")
async def list_goals(
    service: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> list[GoalContract]:
    return await service.list_goals(owner_id=principal.user_id)


@router.get("/dashboard")
async def dashboard(
    service: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    collections: Annotated[CollectionService, Depends(get_collection_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    goals = await service.list_goals(owner_id=principal.user_id)
    histories = await what_if.histories_for_owned([goal.goal_id for goal in goals])
    views = []
    for row in await collections.list_for(principal.user_id):
        views.append(await collections.view(row, goals, histories))
    return {
        "goals": [goal.model_dump(mode="json") for goal in goals],
        "histories": histories,
        "collections": [item.model_dump(mode="json") for item in views],
    }


@router.post("/archive")
async def archive_goals(
    body: ArchiveBody,
    service: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, int]:
    return await service.archive_goals(body.goal_ids, principal.user_id)


@router.delete("/{goal_id}")
async def archive_goal(
    goal_id: UUID,
    service: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, str]:
    await service.archive_goal(goal_id, principal.user_id)
    return {"status": "archived"}


@router.post("/{goal_id}/restore")
async def restore_goal(
    goal_id: UUID,
    service: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, str]:
    await service.restore_goal(goal_id, principal.user_id)
    return {"status": "active"}


@router.get("/{goal_id}")
async def get_goal(
    goal_id: UUID,
    service: Annotated[GoalService, Depends(get_goal_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> GoalContract:
    return await service.get_goal(goal_id, owner_id=principal.user_id)
