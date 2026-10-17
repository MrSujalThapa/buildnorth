from typing import Protocol
from uuid import UUID

from personal_markets.goals.domain import GoalContract


class GoalRepository(Protocol):
    async def list(self) -> list[GoalContract]: ...

    async def get(self, goal_id: UUID) -> GoalContract | None: ...

    async def upsert_seed(self, goal: GoalContract) -> bool: ...

    async def create(self, goal: GoalContract, user_id: UUID) -> GoalContract: ...
