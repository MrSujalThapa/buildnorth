from uuid import UUID

from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.repository import GoalRepository


class GoalService:
    def __init__(self, repository: GoalRepository) -> None:
        self._repository = repository

    async def list_goals(self) -> list[GoalContract]:
        return await self._repository.list()

    async def get_goal(self, goal_id: UUID) -> GoalContract:
        goal = await self._repository.get(goal_id)
        if goal is None:
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")
        return goal

    async def get_goal_by_string(self, goal_id: str) -> GoalContract:
        return await self.get_goal(UUID(goal_id))

    async def create_goal(self, goal: GoalContract, user_id: UUID) -> GoalContract:
        return await self._repository.create(goal, user_id)
