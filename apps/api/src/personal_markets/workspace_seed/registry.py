from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.workspace_seed.fixtures import SEED_VERSION


class InMemorySeedRegistry:
    def __init__(self) -> None:
        self._rows: dict[UUID, list[tuple[str, UUID]]] = {}

    async def list(self, owner_id: UUID) -> list[tuple[str, UUID]]:
        return list(self._rows.get(owner_id, []))

    async def add(self, owner_id: UUID, entity_type: str, entity_id: UUID) -> None:
        rows = self._rows.setdefault(owner_id, [])
        if (entity_type, entity_id) not in rows:
            rows.append((entity_type, entity_id))


class PostgresSeedRegistry:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list(self, owner_id: UUID) -> list[tuple[str, UUID]]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select entity_type, entity_id from workspace_seed_records "
                        "where owner_id = :owner_id order by created_at"
                    ),
                    {"owner_id": owner_id},
                )
            ).all()
        return [(str(row[0]), row[1]) for row in rows]

    async def add(self, owner_id: UUID, entity_type: str, entity_id: UUID) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    "insert into workspace_seed_records "
                    "(owner_id, seed_version, entity_type, entity_id) "
                    "values (:owner_id, :version, :entity_type, :entity_id) "
                    "on conflict do nothing"
                ),
                {
                    "owner_id": owner_id,
                    "version": SEED_VERSION,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                },
            )
