import asyncio
import time
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.collections.service import CollectionService
from personal_markets.goals.domain import GoalContract
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
    workflow: Annotated[Any, Depends(get_agent_workflow)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    started = time.perf_counter()
    goals = await service.list_goals(owner_id=principal.user_id)
    goals_ms = round((time.perf_counter() - started) * 1000)
    parallel_started = time.perf_counter()
    histories, rows, creations = await asyncio.gather(
        what_if.histories_for_owned([goal.goal_id for goal in goals]),
        collections.list_for(principal.user_id),
        workflow.creations_for_goals([goal.goal_id for goal in goals], principal.user_id),
    )
    reads_ms = round((time.perf_counter() - parallel_started) * 1000)
    views = []
    blocked = {goal_id for goal_id, snapshot in creations.items()
               if blocks_current_forecast(snapshot)}
    for row in rows:
        views.append(await collections.view(row, goals, histories, blocked))
    structlog.get_logger(__name__).info(
        "dashboard_timing", goals_ms=goals_ms, reads_ms=reads_ms,
        total_ms=round((time.perf_counter() - started) * 1000),
        goal_count=len(goals), collection_count=len(rows),
    )
    return {
        "goals": [goal.model_dump(mode="json") for goal in goals],
        "histories": histories,
        "creation_states": {
            str(goal_id): {
                "status": snapshot.status,
                "critic_decision": snapshot.critic.decision if snapshot.critic else None,
            }
            for goal_id, snapshot in creations.items()
        },
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
