from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.wiring import get_goal_service

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


@router.get("")
async def list_goals(
    service: Annotated[GoalService, Depends(get_goal_service)],
) -> list[GoalContract]:
    return await service.list_goals()


@router.get("/{goal_id}")
async def get_goal(
    goal_id: UUID, service: Annotated[GoalService, Depends(get_goal_service)]
) -> GoalContract:
    return await service.get_goal(goal_id)
