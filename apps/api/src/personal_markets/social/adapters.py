from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import (
    ForecastStatus,
    GoalContract,
    GoalType,
    ResourceConstraints,
)
from personal_markets.social.domain import ActivityType, Visibility


class InMemorySocialRepository:
    def __init__(self, goals: InMemoryGoalRepository | None = None) -> None:
        self._goals = goals or InMemoryGoalRepository()
        self._visibility: dict[UUID, Visibility] = {}
        self._published_at: dict[UUID, datetime | None] = {}
        self._blueprint: dict[UUID, dict[str, Any]] = {}
        self._fork: dict[UUID, tuple[UUID, UUID]] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}
        self._stars: set[tuple[UUID, UUID]] = set()
        self._follows: dict[tuple[UUID, UUID], datetime] = {}
        self._activity: list[tuple[UUID, ActivityType, date, UUID | None]] = []
        self._history: dict[UUID, list[dict[str, Any]]] = {}
        self._evidence_metrics: dict[UUID, dict[str, str]] = {}
        self._updated: dict[UUID, datetime] = {}

    def bind_goals(self, goals: InMemoryGoalRepository) -> None:
        self._goals = goals

    def add_history(self, goal_id: UUID, points: list[dict[str, Any]]) -> None:
        self._history[goal_id] = points

    async def owner_id(self, goal_id: UUID) -> UUID | None:
        return self._goals._owners.get(goal_id)

    async def visibility(self, goal_id: UUID) -> Visibility | None:
        if goal_id not in self._goals._goals or not self._goals._active(goal_id):
            return None
        return self._visibility.get(goal_id, "private")

    async def set_visibility(
        self,
        goal_id: UUID,
        owner_id: UUID,
        visibility: Visibility,
        blueprint: dict[str, Any],
        published_at: datetime | None,
    ) -> bool:
        if self._goals._owners.get(goal_id) != owner_id or not self._goals._active(goal_id):
            return False
        self._visibility[goal_id] = visibility
        self._blueprint[goal_id] = blueprint
        self._published_at[goal_id] = published_at
        self._updated[goal_id] = datetime.now(UTC)
        return True

    async def public_goal_ids(self, goal_ids: list[UUID]) -> set[UUID]:
        return {
            goal_id
            for goal_id in goal_ids
            if self._visibility.get(goal_id) == "public" and self._goals._active(goal_id)
        }

    def _row(self, goal_id: UUID) -> dict[str, Any] | None:
        goal = self._goals._goals.get(goal_id)
        owner = self._goals._owners.get(goal_id)
        if goal is None or owner is None or not self._goals._active(goal_id):
            return None
        source = self._fork.get(goal_id)
        return {
            "id": goal_id,
            "user_id": owner,
            "title": goal.title,
            "goal_type": goal.goal_type.value,
            "success_definition_json": goal.success_definition,
            "state_dimensions_json": list(goal.state_dimensions),
            "version": goal.version,
            "deadline": goal.deadline,
            "model_requirements_json": goal.model_requirements,
            "visibility": self._visibility.get(goal_id, "private"),
            "published_at": self._published_at.get(goal_id),
            "public_blueprint_json": self._blueprint.get(goal_id) or {},
            "forked_from_goal_id": source[0] if source else None,
            "forked_from_user_id": source[1] if source else None,
            "updated_at": self._updated.get(goal_id, datetime.now(UTC)),
            "status": self._goals._status.get(goal_id, "active"),
        }

    def _matches(self, row: dict[str, Any], query: str | None, category: str | None) -> bool:
        if category and str(row["goal_type"]) != category:
            return False
        if not query:
            return True
        needle = query.lower()
        blob = f"{row['title']} {row.get('public_blueprint_json')}"
        return needle in blob.lower()

    async def search_public(
        self,
        *,
        query: str | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for goal_id in self._goals._goals
            if (row := self._row(goal_id))
            and row["visibility"] == "public"
            and self._matches(row, query, category)
        ]
        stars = await self.star_counts([row["id"] for row in rows])
        forks = await self.fork_counts([row["id"] for row in rows])

        def key(row: dict[str, Any]) -> tuple[Any, ...]:
            if sort == "stars":
                return (-stars.get(row["id"], 0), row["title"], str(row["id"]))
            if sort == "forks":
                return (-forks.get(row["id"], 0), row["title"], str(row["id"]))
            stamp = (
                row.get("published_at") or row.get("updated_at") or datetime.min.replace(tzinfo=UTC)
            )
            return (-stamp.timestamp(), row["title"], str(row["id"]))

        rows.sort(key=key)
        return rows[offset : offset + limit]

    async def count_public(self, *, query: str | None, category: str | None) -> int:
        return sum(
            1
            for goal_id in self._goals._goals
            if (row := self._row(goal_id))
            and row["visibility"] == "public"
            and self._matches(row, query, category)
        )

    async def public_goals_for_user(
        self, user_id: UUID, *, query: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for goal_id, owner in self._goals._owners.items()
            if owner == user_id
            and (row := self._row(goal_id))
            and row["visibility"] == "public"
            and self._matches(row, query, None)
        ]
        rows.sort(key=lambda row: row["title"])
        return rows[offset : offset + limit]

    async def owner_goals(
        self,
        user_id: UUID,
        *,
        query: str | None,
        visibility: Visibility | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for goal_id, owner in self._goals._owners.items()
            if owner == user_id
            and (row := self._row(goal_id))
            and (visibility is None or row["visibility"] == visibility)
            and self._matches(row, query, None)
        ]
        rows.sort(key=lambda row: row["title"])
        return rows[offset : offset + limit]

    async def get_goal_row(self, goal_id: UUID) -> dict[str, Any] | None:
        return self._row(goal_id)

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
    ) -> tuple[dict[str, Any], bool]:
        if idempotency_key:
            existing_id = self._idempotency.get((owner_id, idempotency_key))
            if existing_id and (row := self._row(existing_id)):
                return row, False
        goal = GoalContract(
            goal_id=goal_id,
            title=title,
            goal_type=GoalType(goal_type),
            success_definition=success_definition,
            deadline=deadline,
            resource_constraints=ResourceConstraints.model_validate(resource_constraints),
            state_dimensions=state_dimensions,
            model_requirements=model_requirements,
            forecast_status=ForecastStatus.EXPLORATORY,
        )
        await self._goals.create(goal, owner_id)
        self._visibility[goal_id] = "private"
        self._fork[goal_id] = (source_goal_id, source_user_id)
        self._updated[goal_id] = datetime.now(UTC)
        if idempotency_key:
            self._idempotency[(owner_id, idempotency_key)] = goal_id
        row = self._row(goal_id)
        assert row is not None
        return row, True

    async def star(self, user_id: UUID, goal_id: UUID) -> bool:
        key = (user_id, goal_id)
        if key in self._stars:
            return False
        self._stars.add(key)
        return True

    async def unstar(self, user_id: UUID, goal_id: UUID) -> bool:
        key = (user_id, goal_id)
        if key not in self._stars:
            return False
        self._stars.remove(key)
        return True

    async def starred(self, user_id: UUID, goal_id: UUID) -> bool:
        return (user_id, goal_id) in self._stars

    async def star_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]:
        counts = {goal_id: 0 for goal_id in goal_ids}
        for _, goal_id in self._stars:
            if goal_id in counts:
                counts[goal_id] += 1
        return counts

    async def starred_goal_ids(self, user_id: UUID, goal_ids: list[UUID]) -> set[UUID]:
        return {goal_id for goal_id in goal_ids if (user_id, goal_id) in self._stars}

    async def list_starred_public(
        self, user_id: UUID, *, viewer_id: UUID | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        rows = []
        for star_user, goal_id in self._stars:
            if star_user != user_id:
                continue
            row = self._row(goal_id)
            if row is None:
                continue
            owner = row["user_id"]
            if row["visibility"] != "public" and viewer_id != owner:
                continue
            rows.append(row)
        rows.sort(key=lambda row: row["title"])
        return rows[offset : offset + limit]

    async def fork_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]:
        counts = {goal_id: 0 for goal_id in goal_ids}
        for source_goal_id, _ in self._fork.values():
            if source_goal_id in counts:
                counts[source_goal_id] += 1
        return counts

    async def follow(self, follower_id: UUID, followee_id: UUID) -> bool:
        if follower_id == followee_id:
            return False
        key = (follower_id, followee_id)
        if key in self._follows:
            return False
        self._follows[key] = datetime.now(UTC)
        return True

    async def unfollow(self, follower_id: UUID, followee_id: UUID) -> bool:
        return self._follows.pop((follower_id, followee_id), None) is not None

    async def following(self, follower_id: UUID, followee_id: UUID) -> bool:
        return (follower_id, followee_id) in self._follows

    async def follow_counts(self, user_id: UUID) -> tuple[int, int]:
        followers = sum(1 for _, followee in self._follows if followee == user_id)
        following = sum(1 for follower, _ in self._follows if follower == user_id)
        return followers, following

    async def followers(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]:
        rows = [
            (follower, stamp)
            for (follower, followee), stamp in self._follows.items()
            if followee == user_id
        ]
        rows.sort(key=lambda item: item[1], reverse=True)
        return rows[offset : offset + limit]

    async def following_list(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]:
        rows = [
            (followee, stamp)
            for (follower, followee), stamp in self._follows.items()
            if follower == user_id
        ]
        rows.sort(key=lambda item: item[1], reverse=True)
        return rows[offset : offset + limit]

    async def record_activity(
        self, user_id: UUID, event_type: ActivityType, occurred_on: date, goal_id: UUID | None
    ) -> None:
        key = (user_id, event_type, occurred_on, goal_id)
        if key in self._activity:
            return
        self._activity.append(key)

    async def activity_counts(
        self,
        user_id: UUID,
        start: date,
        end: date,
        *,
        public_only: bool = False,
        include_fixtures: bool = False,
    ) -> dict[date, int]:
        counts: dict[date, int] = {}
        for owner, _type, day, goal_id in self._activity:
            if public_only and (
                goal_id is None
                or self._visibility.get(goal_id) != "public"
                or not self._goals._active(goal_id)
            ):
                continue
            if owner == user_id and start <= day <= end:
                counts[day] = counts.get(day, 0) + 1
        return counts

    async def history_for_goals(self, goal_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        return {goal_id: list(self._history.get(goal_id, [])) for goal_id in goal_ids}

    def add_evidence_metrics(self, goal_id: UUID, metrics: dict[str, str]) -> None:
        self._evidence_metrics.setdefault(goal_id, {}).update(metrics)

    async def published_updates(self, goal_id: UUID) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._history.get(goal_id, [])
            if str(row.get("source_kind") or "published_forecast") == "published_forecast"
        ]
        return sorted(rows, key=lambda row: row["created_at"])

    async def evidence_metrics(self, goal_id: UUID, evidence_ids: list[str]) -> dict[str, str]:
        linked = self._evidence_metrics.get(goal_id, {})
        return {item: linked[item] for item in evidence_ids if item in linked}

    async def discover_creators(self, limit: int) -> list[UUID]:
        counts: dict[UUID, int] = {}
        for goal_id, owner in self._goals._owners.items():
            if self._visibility.get(goal_id) == "public" and self._goals._active(goal_id):
                counts[owner] = counts.get(owner, 0) + 1
        ranked = sorted(counts, key=lambda user_id: (-counts[user_id], str(user_id)))
        return ranked[:limit]
