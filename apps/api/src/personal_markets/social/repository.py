from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from personal_markets.social.domain import ActivityType, Visibility


class SocialRepository(Protocol):
    async def owner_id(self, goal_id: UUID) -> UUID | None: ...

    async def visibility(self, goal_id: UUID) -> Visibility | None: ...

    async def set_visibility(
        self,
        goal_id: UUID,
        owner_id: UUID,
        visibility: Visibility,
        blueprint: dict[str, Any],
        published_at: datetime | None,
    ) -> bool: ...

    async def public_goal_ids(self, goal_ids: list[UUID]) -> set[UUID]: ...

    async def search_public(
        self,
        *,
        query: str | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    async def public_goals_for_user(
        self, user_id: UUID, *, query: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    async def owner_goals(
        self,
        user_id: UUID,
        *,
        query: str | None,
        visibility: Visibility | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    async def get_goal_row(self, goal_id: UUID) -> dict[str, Any] | None: ...

    async def create_fork(
        self,
        *,
        goal_id: UUID,
        owner_id: UUID,
        title: str,
        goal_type: str,
        success_definition: dict[str, Any],
        deadline: datetime,
        resource_constraints: dict[str, Any],
        state_dimensions: list[str],
        model_requirements: dict[str, Any],
        source_goal_id: UUID,
        source_user_id: UUID,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool]: ...

    async def star(self, user_id: UUID, goal_id: UUID) -> bool: ...

    async def unstar(self, user_id: UUID, goal_id: UUID) -> bool: ...

    async def starred(self, user_id: UUID, goal_id: UUID) -> bool: ...

    async def star_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]: ...

    async def starred_goal_ids(self, user_id: UUID, goal_ids: list[UUID]) -> set[UUID]: ...

    async def list_starred_public(
        self, user_id: UUID, *, viewer_id: UUID | None, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    async def fork_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]: ...

    async def follow(self, follower_id: UUID, followee_id: UUID) -> bool: ...

    async def unfollow(self, follower_id: UUID, followee_id: UUID) -> bool: ...

    async def following(self, follower_id: UUID, followee_id: UUID) -> bool: ...

    async def follow_counts(self, user_id: UUID) -> tuple[int, int]: ...

    async def followers(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]: ...

    async def following_list(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]: ...

    async def record_activity(
        self, user_id: UUID, event_type: ActivityType, occurred_on: date, goal_id: UUID | None
    ) -> None: ...

    async def activity_counts(
        self, user_id: UUID, start: date, end: date, *, public_only: bool = False
    ) -> dict[date, int]: ...

    async def history_for_goals(self, goal_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]: ...

    async def discover_creators(self, limit: int) -> list[UUID]: ...
