from __future__ import annotations

from typing import Any
from uuid import UUID

from personal_markets.goals.domain import GoalContract


class InMemoryGoalRepository:
    def __init__(self) -> None:
        self._goals: dict[UUID, GoalContract] = {}
        self._owners: dict[UUID, UUID] = {}
        self._status: dict[UUID, str] = {}

    def _active(self, goal_id: UUID) -> bool:
        return self._status.get(goal_id, "active") == "active"

    async def list(self) -> list[GoalContract]:
        return sorted(
            [goal for goal_id, goal in self._goals.items() if self._active(goal_id)],
            key=lambda goal: goal.title,
        )

    async def list_for_user(self, user_id: UUID) -> list[GoalContract]:
        return sorted(
            [
                goal
                for goal_id, goal in self._goals.items()
                if self._owners.get(goal_id) == user_id and self._active(goal_id)
            ],
            key=lambda goal: goal.title,
        )

    async def get(self, goal_id: UUID) -> GoalContract | None:
        if not self._active(goal_id):
            return None
        return self._goals.get(goal_id)

    async def get_for_user(self, goal_id: UUID, user_id: UUID) -> GoalContract | None:
        if self._owners.get(goal_id) != user_id or not self._active(goal_id):
            return None
        return self._goals.get(goal_id)

    async def upsert_seed(self, goal: GoalContract) -> bool:
        created = goal.goal_id not in self._goals
        self._goals[goal.goal_id] = goal
        self._status[goal.goal_id] = "active"
        return created

    async def create(self, goal: GoalContract, user_id: UUID) -> GoalContract:
        if goal.goal_id in self._goals:
            return self._goals[goal.goal_id]
        self._goals[goal.goal_id] = goal
        self._owners[goal.goal_id] = user_id
        self._status[goal.goal_id] = "active"
        return goal

    async def archive_for_user(self, goal_id: UUID, user_id: UUID) -> bool:
        if self._owners.get(goal_id) != user_id or goal_id not in self._goals:
            return False
        if not self._active(goal_id):
            return False
        self._status[goal_id] = "archived"
        return True

    async def restore_for_user(self, goal_id: UUID, user_id: UUID) -> bool:
        if self._owners.get(goal_id) != user_id or goal_id not in self._goals:
            return False
        if self._active(goal_id):
            return False
        self._status[goal_id] = "active"
        return True

    async def merge_requirements(
        self, goal_id: UUID, user_id: UUID, patch: dict[str, Any]
    ) -> GoalContract | None:
        if self._owners.get(goal_id) != user_id:
            return None
        goal = self._goals.get(goal_id)
        if goal is None:
            return None
        merged = {**goal.model_requirements, **patch}
        updated = goal.model_copy(update={"model_requirements": merged})
        self._goals[goal_id] = updated
        return updated
