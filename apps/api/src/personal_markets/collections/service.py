from __future__ import annotations

from typing import Any
from uuid import UUID

from personal_markets.collections.domain import (
    CollectionRecord,
    CollectionSeries,
    CollectionView,
)
from personal_markets.collections.portfolio import portfolio_summary
from personal_markets.collections.progress import aggregate_progress
from personal_markets.collections.repository import PALETTE, new_collection
from personal_markets.core.errors import ConflictError, ForbiddenError, ResourceNotFoundError
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService


class CollectionService:
    def __init__(self, repository, goals: GoalService) -> None:
        self._repository = repository
        self._goals = goals

    async def list_for(self, owner_id: UUID) -> list[CollectionRecord]:
        return await self._repository.list_for_user(owner_id)

    async def get_for(self, collection_id: UUID, owner_id: UUID) -> CollectionRecord:
        row = await self._repository.get_for_user(collection_id, owner_id)
        if row is None:
            raise ResourceNotFoundError(f"Collection {collection_id} was not found")
        return row

    async def create(
        self,
        owner_id: UUID,
        *,
        name: str,
        description: str = "",
        icon: str | None = None,
        color: str | None = None,
        goal_ids: list[UUID] | None = None,
    ) -> CollectionRecord:
        existing = await self._repository.list_for_user(owner_id)
        members = await self._owned_ids(owner_id, goal_ids or [])
        return await self._repository.create(
            new_collection(
                owner_id,
                name=name,
                description=description,
                icon=icon,
                color=color or PALETTE[len(existing) % len(PALETTE)],
                position=len(existing),
                goal_ids=members,
            )
        )

    async def update(
        self,
        collection_id: UUID,
        owner_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        color: str | None = None,
        goal_ids: list[UUID] | None = None,
        position: int | None = None,
    ) -> CollectionRecord:
        row = await self.get_for(collection_id, owner_id)
        if name is not None and any(
            item.collection_id != collection_id and item.name.casefold() == name.strip().casefold()
            for item in await self._repository.list_for_user(owner_id)
        ):
            raise ConflictError("A collection with that name already exists")
        members = row.goal_ids if goal_ids is None else await self._owned_ids(owner_id, goal_ids)
        updated = row.model_copy(
            update={
                "name": name.strip() if name is not None else row.name,
                "description": description.strip() if description is not None else row.description,
                "icon": icon if icon is not None else row.icon,
                "color": color if color is not None else row.color,
                "position": row.position if position is None else position,
                "goal_ids": members,
            }
        )
        return await self._repository.update(updated)

    async def delete(self, collection_id: UUID, owner_id: UUID) -> None:
        if not await self._repository.delete(collection_id, owner_id):
            raise ResourceNotFoundError(f"Collection {collection_id} was not found")

    async def add_goals(
        self, collection_id: UUID, owner_id: UUID, goal_ids: list[UUID]
    ) -> CollectionRecord:
        row = await self.get_for(collection_id, owner_id)
        owned = await self._owned_ids(owner_id, goal_ids)
        merged = list(row.goal_ids)
        for goal_id in owned:
            if goal_id not in merged:
                merged.append(goal_id)
        return await self.update(collection_id, owner_id, goal_ids=merged)

    async def remove_goal(
        self, collection_id: UUID, owner_id: UUID, goal_id: UUID
    ) -> CollectionRecord:
        row = await self.get_for(collection_id, owner_id)
        remaining = [item for item in row.goal_ids if item != goal_id]
        return await self.update(collection_id, owner_id, goal_ids=remaining)

    async def view(
        self,
        row: CollectionRecord,
        goals: list[GoalContract],
        histories: dict[str, list[dict[str, Any]]],
        blocked_goal_ids: set[UUID] | None = None,
    ) -> CollectionView:
        by_id = {goal.goal_id: goal for goal in goals}
        members = [by_id[goal_id] for goal_id in row.goal_ids if goal_id in by_id]
        series: list[CollectionSeries] = []
        for index, goal in enumerate(members):
            publication = goal.model_requirements.get("last_publication")
            withheld = (
                goal.goal_id in (blocked_goal_ids or set())
                or isinstance(publication, dict) and publication.get("status") == "withheld"
            )
            points = []
            for point in histories.get(str(goal.goal_id), []):
                payload = (
                    point.model_dump(mode="json") if hasattr(point, "model_dump") else dict(point)
                )
                probability = payload.get("probability")
                created = payload.get("created_at")
                if probability is None:
                    continue
                points.append({"timestamp": created, "value": float(probability) * 100})
            series.append(
                CollectionSeries(
                    goal_id=goal.goal_id,
                    title=goal.title,
                    color=PALETTE[index % len(PALETTE)],
                    points=points,
                    withheld=withheld,
                )
            )
        odds, change, coverage = portfolio_summary(series)
        return CollectionView(
            collection=row,
            progress=aggregate_progress(members),
            series=series,
            portfolio_odds=odds,
            change_pp=change,
            priced_goals=coverage,
            total_goals=len(members),
        )

    async def _owned_ids(self, owner_id: UUID, goal_ids: list[UUID]) -> list[UUID]:
        owned: list[UUID] = []
        for goal_id in goal_ids:
            try:
                await self._goals.get_goal(goal_id, owner_id=owner_id)
            except ResourceNotFoundError as error:
                raise ForbiddenError("goals must belong to the signed-in user") from error
            owned.append(goal_id)
        return owned
