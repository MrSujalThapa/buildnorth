"""Owner-scoped, bounded profile photo storage."""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.core.config import get_settings
from personal_markets.persistence.database import create_engine, transaction


class InMemoryPhotoStore:
    def __init__(self) -> None:
        self._photos: dict[UUID, bytes] = {}

    async def get(self, user_id: UUID) -> bytes | None:
        return self._photos.get(user_id)

    async def put(self, user_id: UUID, content: bytes) -> None:
        self._photos[user_id] = content

    async def delete(self, user_id: UUID) -> None:
        self._photos.pop(user_id, None)


class PostgresPhotoStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, user_id: UUID) -> bytes | None:
        async with self._engine.connect() as connection:
            return (await connection.execute(
                text("select content from profile_photos where user_id = :user_id"),
                {"user_id": user_id},
            )).scalar_one_or_none()

    async def put(self, user_id: UUID, content: bytes) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(text("""
                insert into profile_photos (user_id, content_type, content)
                values (:user_id, 'image/webp', :content)
                on conflict (user_id) do update set
                  content = excluded.content, updated_at = now()
            """), {"user_id": user_id, "content": content})

    async def delete(self, user_id: UUID) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("delete from profile_photos where user_id = :user_id"),
                {"user_id": user_id},
            )


@lru_cache
def get_photo_store() -> InMemoryPhotoStore | PostgresPhotoStore:
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresPhotoStore(create_engine(settings.database_url))
    return InMemoryPhotoStore()
