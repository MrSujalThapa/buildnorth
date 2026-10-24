from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.collections.service import CollectionService
from personal_markets.goals.publication import blocks_current_forecast
from personal_markets.goals.service import GoalService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.what_if.service import WhatIfService
from personal_markets.wiring import (
    get_agent_workflow,
    get_collection_service,
    get_goal_service,
    get_what_if_service,
)

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=16)
    goal_ids: list[UUID] = Field(default_factory=list)


class CollectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=16)
    goal_ids: list[UUID] | None = None
    position: int | None = None


class MemberBody(BaseModel):
    goal_ids: list[UUID] = Field(min_length=1)


async def _view_payload(
    service: CollectionService,
    goals: GoalService,
    what_if: WhatIfService,
    workflow: Any,
    row,
    owner_id: UUID,
) -> dict[str, Any]:
    owned = await goals.list_goals(owner_id=owner_id)
    histories = await what_if.histories_for_owned(row.goal_ids)
    creations = await workflow.creations_for_goals(row.goal_ids, owner_id)
    blocked = {goal_id for goal_id, snapshot in creations.items()
               if blocks_current_forecast(snapshot)}
    view = await service.view(row, owned, histories, blocked)
    return view.model_dump(mode="json")


@router.get("")
async def list_collections(
    service: Annotated[CollectionService, Depends(get_collection_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> list[dict[str, Any]]:
    rows = await service.list_for(principal.user_id)
    return [
        await _view_payload(service, goals, what_if, workflow, row, principal.user_id)
        for row in rows
    ]


@router.post("")
async def create_collection(
    body: CollectionBody,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    row = await service.create(
        principal.user_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        goal_ids=body.goal_ids,
    )
    return await _view_payload(service, goals, what_if, workflow, row, principal.user_id)


@router.get("/{collection_id}")
async def get_collection(
    collection_id: UUID,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    row = await service.get_for(collection_id, principal.user_id)
    return await _view_payload(service, goals, what_if, workflow, row, principal.user_id)


@router.patch("/{collection_id}")
async def patch_collection(
    collection_id: UUID,
    body: CollectionPatch,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    row = await service.update(
        collection_id,
        principal.user_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        goal_ids=body.goal_ids,
        position=body.position,
    )
    return await _view_payload(service, goals, what_if, workflow, row, principal.user_id)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: UUID,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, str]:
    await service.delete(collection_id, principal.user_id)
    return {"status": "deleted"}


@router.post("/{collection_id}/goals")
async def add_collection_goals(
    collection_id: UUID,
    body: MemberBody,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    what_if: Annotated[WhatIfService, Depends(get_what_if_service)],
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    row = await service.add_goals(collection_id, principal.user_id, body.goal_ids)
    return await _view_payload(service, goals, what_if, workflow, row, principal.user_id)
