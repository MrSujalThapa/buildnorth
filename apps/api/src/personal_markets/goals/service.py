from uuid import UUID

from personal_markets.core.errors import ForbiddenError, ResourceNotFoundError
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.publication import publication_snapshot
from personal_markets.goals.repository import GoalRepository
from personal_markets.ports import CriticArtifact


class GoalService:
    def __init__(self, repository: GoalRepository) -> None:
        self._repository = repository

    async def list_goals(self, owner_id: UUID | None = None) -> list[GoalContract]:
        if owner_id is None:
            return await self._repository.list()
        return await self._repository.list_for_user(owner_id)

    async def get_goal(self, goal_id: UUID, owner_id: UUID | None = None) -> GoalContract:
        if owner_id is not None:
            goal = await self._repository.get_for_user(goal_id, owner_id)
        else:
            goal = await self._repository.get(goal_id)
        if goal is None:
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")
        return goal

    async def get_goal_by_string(self, goal_id: str, owner_id: UUID | None = None) -> GoalContract:
        return await self.get_goal(UUID(goal_id), owner_id=owner_id)

    async def create_goal(self, goal: GoalContract, user_id: UUID) -> GoalContract:
        return await self._repository.create(goal, user_id)

    async def archive_goal(self, goal_id: UUID, owner_id: UUID) -> None:
        archived = await self._repository.archive_for_user(goal_id, owner_id)
        if not archived:
            existing = await self._repository.get(goal_id)
            if existing is not None:
                raise ForbiddenError("only the owner can archive this goal")
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")

    async def archive_goals(self, goal_ids: list[UUID], owner_id: UUID) -> dict[str, int]:
        archived = 0
        missing = 0
        for goal_id in goal_ids:
            if await self._repository.archive_for_user(goal_id, owner_id):
                archived += 1
            else:
                missing += 1
        return {"archived": archived, "skipped": missing}

    async def restore_goal(self, goal_id: UUID, owner_id: UUID) -> None:
        restored = await self._repository.restore_for_user(goal_id, owner_id)
        if not restored:
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")

    async def record_publication(
        self,
        goal_id: UUID,
        owner_id: UUID,
        critic: CriticArtifact,
        status: str,
    ) -> None:
        await self._repository.merge_requirements(
            goal_id, owner_id, {"last_publication": publication_snapshot(critic, status)}
        )
