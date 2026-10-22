from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.collections.domain import CollectionRecord
from personal_markets.persistence.database import autocommit_connection, transaction

PALETTE = ("#1f8f86", "#c85f3e", "#5b6ee1", "#c9a227", "#7a5c8e", "#3d7ea6")


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self._rows: dict[UUID, CollectionRecord] = {}

    async def list_for_user(self, user_id: UUID) -> list[CollectionRecord]:
        return sorted(
            [row for row in self._rows.values() if row.owner_id == user_id],
            key=lambda row: (row.position, row.name),
        )

    async def get_for_user(self, collection_id: UUID, user_id: UUID) -> CollectionRecord | None:
        row = self._rows.get(collection_id)
        if row is None or row.owner_id != user_id:
            return None
        return row

    async def create(self, row: CollectionRecord) -> CollectionRecord:
        self._rows[row.collection_id] = row
        return row

    async def update(self, row: CollectionRecord) -> CollectionRecord:
        self._rows[row.collection_id] = row
        return row

    async def delete(self, collection_id: UUID, user_id: UUID) -> bool:
        row = self._rows.get(collection_id)
        if row is None or row.owner_id != user_id:
            return False
        del self._rows[collection_id]
        return True


class PostgresCollectionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_for_user(self, user_id: UUID) -> list[CollectionRecord]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select c.*, coalesce(
                          (
                            select array_agg(cg.goal_id order by cg.position, cg.added_at)
                            from collection_goals cg
                            join goals g on g.id = cg.goal_id and g.status = 'active'
                            where cg.collection_id = c.id
                          ),
                          '{}'::uuid[]
                        ) as goal_ids
                        from collections c
                        where c.user_id = :user_id
                        order by c.position, c.created_at
                        """
                    ),
                    {"user_id": user_id},
                )
            ).mappings()
            return [self._to_domain(dict(row)) for row in rows]

    async def get_for_user(self, collection_id: UUID, user_id: UUID) -> CollectionRecord | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            select c.*, coalesce(
                              (
                                select array_agg(cg.goal_id order by cg.position, cg.added_at)
                                from collection_goals cg
                                join goals g on g.id = cg.goal_id and g.status = 'active'
                                where cg.collection_id = c.id
                              ),
                              '{}'::uuid[]
                            ) as goal_ids
                            from collections c
                            where c.id = :id and c.user_id = :user_id
                            """
                        ),
                        {"id": collection_id, "user_id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_domain(dict(row)) if row else None

    async def create(self, row: CollectionRecord) -> CollectionRecord:
        now = datetime.now(UTC)
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    """
                    insert into collections (id, user_id, name, description, icon, color, position)
                    values (:id, :user_id, :name, :description, :icon, :color, :position)
                    """
                ),
                {
                    "id": row.collection_id,
                    "user_id": row.owner_id,
                    "name": row.name,
                    "description": row.description,
                    "icon": row.icon,
                    "color": row.color,
                    "position": row.position,
                },
            )
            await self._replace_members(connection, row.collection_id, row.goal_ids)
        stored = await self.get_for_user(row.collection_id, row.owner_id)
        assert stored is not None
        stored = stored.model_copy(update={"created_at": stored.created_at or now})
        return stored

    async def update(self, row: CollectionRecord) -> CollectionRecord:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    """
                    update collections
                    set name = :name, description = :description, icon = :icon,
                        color = :color, position = :position, updated_at = now()
                    where id = :id and user_id = :user_id
                    """
                ),
                {
                    "id": row.collection_id,
                    "user_id": row.owner_id,
                    "name": row.name,
                    "description": row.description,
                    "icon": row.icon,
                    "color": row.color,
                    "position": row.position,
                },
            )
            await self._replace_members(connection, row.collection_id, row.goal_ids)
        stored = await self.get_for_user(row.collection_id, row.owner_id)
        assert stored is not None
        return stored

    async def delete(self, collection_id: UUID, user_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("delete from collections where id = :id and user_id = :user_id"),
                {"id": collection_id, "user_id": user_id},
            )
        return bool(result.rowcount)

    @staticmethod
    async def _replace_members(connection, collection_id: UUID, goal_ids: list[UUID]) -> None:
        await connection.execute(
            text("delete from collection_goals where collection_id = :id"),
            {"id": collection_id},
        )
        for index, goal_id in enumerate(goal_ids):
            await connection.execute(
                text(
                    """
                    insert into collection_goals (collection_id, goal_id, position)
                    values (:collection_id, :goal_id, :position)
                    on conflict (collection_id, goal_id) do update set position = excluded.position
                    """
                ),
                {"collection_id": collection_id, "goal_id": goal_id, "position": index},
            )

    @staticmethod
    def _to_domain(row: dict) -> CollectionRecord:
        raw_ids = row.get("goal_ids") or []
        if isinstance(raw_ids, str):
            import json

            raw_ids = json.loads(raw_ids)
        goal_ids = [item if isinstance(item, UUID) else UUID(str(item)) for item in raw_ids]
        return CollectionRecord(
            collection_id=row["id"],
            owner_id=row["user_id"],
            name=row["name"],
            description=row.get("description") or "",
            icon=row.get("icon"),
            color=row.get("color"),
            position=int(row.get("position") or 0),
            goal_ids=goal_ids,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


def new_collection(
    owner_id: UUID,
    *,
    name: str,
    description: str = "",
    icon: str | None = None,
    color: str | None = None,
    position: int = 0,
    goal_ids: list[UUID] | None = None,
) -> CollectionRecord:
    return CollectionRecord(
        collection_id=uuid4(),
        owner_id=owner_id,
        name=name.strip(),
        description=description.strip(),
        icon=icon,
        color=color,
        position=position,
        goal_ids=list(goal_ids or []),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
