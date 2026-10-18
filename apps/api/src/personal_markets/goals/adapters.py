from uuid import UUID

from personal_markets.goals.domain import GoalContract


class InMemoryGoalRepository:
    def __init__(self) -> None:
        self._goals: dict[UUID, GoalContract] = {}
        self._owners: dict[UUID, UUID] = {}

    async def list(self) -> list[GoalContract]:
        return sorted(self._goals.values(), key=lambda goal: goal.title)

    async def list_for_user(self, user_id: UUID) -> list[GoalContract]:
        return sorted(
            [goal for goal_id, goal in self._goals.items() if self._owners.get(goal_id) == user_id],
            key=lambda goal: goal.title,
        )

    async def get(self, goal_id: UUID) -> GoalContract | None:
        return self._goals.get(goal_id)

    async def get_for_user(self, goal_id: UUID, user_id: UUID) -> GoalContract | None:
        if self._owners.get(goal_id) != user_id:
            return None
        return self._goals.get(goal_id)

    async def upsert_seed(self, goal: GoalContract) -> bool:
        created = goal.goal_id not in self._goals
        self._goals[goal.goal_id] = goal
        return created

    async def create(self, goal: GoalContract, user_id: UUID) -> GoalContract:
        if goal.goal_id in self._goals:
            return self._goals[goal.goal_id]
        self._goals[goal.goal_id] = goal
        self._owners[goal.goal_id] = user_id
        return goal
