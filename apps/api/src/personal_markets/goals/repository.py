from __future__ import annotations

from typing import Protocol
from uuid import UUID

from personal_markets.goals.domain import GoalContract


class GoalRepository(Protocol):
    async def list(self) -> list[GoalContract]: ...

    async def list_for_user(self, user_id: UUID) -> list[GoalContract]: ...

    async def get(self, goal_id: UUID) -> GoalContract | None: ...

    async def get_for_user(self, goal_id: UUID, user_id: UUID) -> GoalContract | None: ...

    async def upsert_seed(self, goal: GoalContract) -> bool: ...

    async def create(self, goal: GoalContract, user_id: UUID) -> GoalContract: ...
