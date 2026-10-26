from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.social.domain import ActivityType, Visibility


class PostgresSocialRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def owner_id(self, goal_id: UUID) -> UUID | None:
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text("select user_id from goals where id = :id and status = 'active'"),
                {"id": goal_id},
            )
        return value if isinstance(value, UUID) else None

    async def visibility(self, goal_id: UUID) -> Visibility | None:
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text("select visibility from goals where id = :id and status = 'active'"),
                {"id": goal_id},
            )
        if value == "public":
            return "public"
        if value == "private":
            return "private"
        return None

    async def set_visibility(
        self,
        goal_id: UUID,
        owner_id: UUID,
        visibility: Visibility,
        blueprint: dict[str, Any],
        published_at: datetime | None,
    ) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    """
                    update goals
                    set visibility = :visibility,
                        public_blueprint_json = cast(:blueprint as jsonb),
                        published_at = :published_at,
                        updated_at = now()
                    where id = :id and user_id = :owner and status = 'active'
                    """
                ),
                {
                    "id": goal_id,
                    "owner": owner_id,
                    "visibility": visibility,
                    "blueprint": json.dumps(blueprint),
                    "published_at": published_at,
                },
            )
        return bool(result.rowcount)

    async def public_goal_ids(self, goal_ids: list[UUID]) -> set[UUID]:
        if not goal_ids:
            return set()
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select id from goals where visibility = 'public' and status = 'active'"
                        " and id in :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": goal_ids},
                )
            ).scalars()
            return set(rows)

    def _goal_select(self) -> str:
        return """
            select id, user_id, title, goal_type, success_definition_json, deadline,
                   model_requirements_json, visibility, published_at, public_blueprint_json,
                   forked_from_goal_id, forked_from_user_id, updated_at, status,
                   state_dimensions_json, version
            from goals
        """

    async def search_public(
        self,
        *,
        query: str | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        star_order = "(select count(*) from market_stars s where s.goal_id = goals.id) desc"
        fork_order = "(select count(*) from goals f where f.forked_from_goal_id = goals.id) desc"
        order = {
            "stars": f"{star_order}, published_at desc nulls last, id desc",
            "forks": f"{fork_order}, published_at desc nulls last, id desc",
            "updated": "updated_at desc, id desc",
        }.get(sort, "published_at desc nulls last, updated_at desc, id desc")
        filters = ["visibility = 'public'", "status = 'active'"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if category:
            filters.append("goal_type = :category")
            params["category"] = category
        if query:
            filters.append("(title ilike :needle or public_blueprint_json::text ilike :needle)")
            params["needle"] = f"%{query}%"
        where = " and ".join(filters)
        sql = (
            f"{self._goal_select()} where {where} "
            "order by {order} limit :limit offset :offset".replace("{order}", order)
        )
        async with autocommit_connection(self._engine) as connection:
            rows = (await connection.execute(text(sql), params)).mappings()
            return [dict(row) for row in rows]

    async def count_public(self, *, query: str | None, category: str | None) -> int:
        filters = ["visibility = 'public'", "status = 'active'"]
        params: dict[str, Any] = {}
        if category:
            filters.append("goal_type = :category")
            params["category"] = category
        if query:
            filters.append("(title ilike :needle or public_blueprint_json::text ilike :needle)")
            params["needle"] = f"%{query}%"
        sql = f"select count(*)::int from goals where {' and '.join(filters)}"
        async with autocommit_connection(self._engine) as connection:
            count = await connection.scalar(text(sql), params)
        return int(count or 0)

    async def public_goals_for_user(
        self, user_id: UUID, *, query: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        filters = "user_id = :user_id and visibility = 'public' and status = 'active'"
        params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
        if query:
            filters += " and title ilike :needle"
            params["needle"] = f"%{query}%"
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        f"{self._goal_select()} where {filters} "
                        "order by updated_at desc limit :limit offset :offset"
                    ),
                    params,
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def owner_goals(
        self,
        user_id: UUID,
        *,
        query: str | None,
        visibility: Visibility | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        filters = "user_id = :user_id and status = 'active'"
        params: dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
        if visibility:
            filters += " and visibility = :visibility"
            params["visibility"] = visibility
        if query:
            filters += " and title ilike :needle"
            params["needle"] = f"%{query}%"
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        f"{self._goal_select()} where {filters} "
                        "order by updated_at desc limit :limit offset :offset"
                    ),
                    params,
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def get_goal_row(self, goal_id: UUID) -> dict[str, Any] | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(f"{self._goal_select()} where id = :id and status = 'active'"),
                        {"id": goal_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row else None

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
        existing = await self._active_fork(owner_id, source_goal_id, idempotency_key)
        if existing:
            return existing, False
        try:
            async with transaction(self._engine) as connection:
                await connection.execute(
                    text(
                        """
                        insert into goals (
                          id, user_id, title, goal_type, success_definition_json, deadline,
                          forecast_status, resource_constraints_json, state_dimensions_json,
                          model_requirements_json, visibility, forked_from_goal_id,
                          forked_from_user_id, fork_idempotency_key
                        ) values (
                          :id, :owner, :title, :goal_type, cast(:success as jsonb), :deadline,
                          'EXPLORATORY', cast(:resources as jsonb), cast(:dimensions as jsonb),
                          cast(:requirements as jsonb), 'private', :source_goal, :source_user, :key
                        )
                        """
                    ),
                    {
                        "id": goal_id,
                        "owner": owner_id,
                        "title": title,
                        "goal_type": goal_type,
                        "success": json.dumps(success_definition),
                        "deadline": deadline,
                        "resources": json.dumps(resource_constraints),
                        "dimensions": json.dumps(state_dimensions),
                        "requirements": json.dumps(model_requirements),
                        "source_goal": source_goal_id,
                        "source_user": source_user_id,
                        "key": idempotency_key,
                    },
                )
        except IntegrityError:
            existing = await self._active_fork(owner_id, source_goal_id, idempotency_key)
            if existing:
                return existing, False
            raise
        row = await self.get_goal_row(goal_id)
        assert row is not None
        return row, True

    async def _active_fork(
        self, owner_id: UUID, source_goal_id: UUID, idempotency_key: str | None
    ) -> dict[str, Any] | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            f"{self._goal_select()} where user_id = :owner and status = 'active'"
                            " and (forked_from_goal_id = :source"
                            " or (:key is not null and fork_idempotency_key = :key))"
                            " order by updated_at desc limit 1"
                        ),
                        {"owner": owner_id, "source": source_goal_id, "key": idempotency_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def star(self, user_id: UUID, goal_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    """
                    insert into market_stars (user_id, goal_id)
                    values (:user_id, :goal_id)
                    on conflict do nothing
                    """
                ),
                {"user_id": user_id, "goal_id": goal_id},
            )
        return bool(result.rowcount)

    async def unstar(self, user_id: UUID, goal_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("delete from market_stars where user_id = :user_id and goal_id = :goal_id"),
                {"user_id": user_id, "goal_id": goal_id},
            )
        return bool(result.rowcount)

    async def starred(self, user_id: UUID, goal_id: UUID) -> bool:
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text("select 1 from market_stars where user_id = :user_id and goal_id = :goal_id"),
                {"user_id": user_id, "goal_id": goal_id},
            )
        return value is not None

    async def star_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]:
        if not goal_ids:
            return {}
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select goal_id, count(*)::int as n from market_stars"
                        " where goal_id in :ids group by goal_id"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": goal_ids},
                )
            ).mappings()
            found = {row["goal_id"]: int(row["n"]) for row in rows}
        return {goal_id: found.get(goal_id, 0) for goal_id in goal_ids}

    async def starred_goal_ids(self, user_id: UUID, goal_ids: list[UUID]) -> set[UUID]:
        if not goal_ids:
            return set()
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select goal_id from market_stars "
                        "where user_id = :user_id and goal_id in :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"user_id": user_id, "ids": goal_ids},
                )
            ).scalars()
            return set(rows)

    async def list_starred_public(
        self, user_id: UUID, *, viewer_id: UUID | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        access = "g.visibility = 'public'"
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
            "viewer": viewer_id,
        }
        if viewer_id is not None:
            access = "(g.visibility = 'public' or g.user_id = :viewer)"
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        f"""
                        select g.id, g.user_id, g.title, g.goal_type, g.success_definition_json,
                               g.deadline, g.model_requirements_json, g.visibility, g.published_at,
                               g.public_blueprint_json,
                               g.forked_from_goal_id, g.forked_from_user_id,
                               g.updated_at, g.status, g.state_dimensions_json, g.version
                        from market_stars s
                        join goals g on g.id = s.goal_id
                        where s.user_id = :user_id and g.status = 'active' and {access}
                        order by s.created_at desc
                        limit :limit offset :offset
                        """
                    ),
                    params,
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def fork_counts(self, goal_ids: list[UUID]) -> dict[UUID, int]:
        if not goal_ids:
            return {}
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        "select forked_from_goal_id as goal_id, count(*)::int as n from goals"
                        " where forked_from_goal_id in :ids group by forked_from_goal_id"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": goal_ids},
                )
            ).mappings()
            found = {row["goal_id"]: int(row["n"]) for row in rows}
        return {goal_id: found.get(goal_id, 0) for goal_id in goal_ids}

    async def follow(self, follower_id: UUID, followee_id: UUID) -> bool:
        if follower_id == followee_id:
            return False
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    """
                    insert into user_follows (follower_id, followee_id)
                    values (:follower, :followee)
                    on conflict do nothing
                    """
                ),
                {"follower": follower_id, "followee": followee_id},
            )
        return bool(result.rowcount)

    async def unfollow(self, follower_id: UUID, followee_id: UUID) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    "delete from user_follows "
                    "where follower_id = :follower and followee_id = :followee"
                ),
                {"follower": follower_id, "followee": followee_id},
            )
        return bool(result.rowcount)

    async def following(self, follower_id: UUID, followee_id: UUID) -> bool:
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text(
                    "select 1 from user_follows "
                    "where follower_id = :follower and followee_id = :followee"
                ),
                {"follower": follower_id, "followee": followee_id},
            )
        return value is not None

    async def follow_counts(self, user_id: UUID) -> tuple[int, int]:
        async with autocommit_connection(self._engine) as connection:
            followers = await connection.scalar(
                text("select count(*)::int from user_follows where followee_id = :id"),
                {"id": user_id},
            )
            following = await connection.scalar(
                text("select count(*)::int from user_follows where follower_id = :id"),
                {"id": user_id},
            )
        return int(followers or 0), int(following or 0)

    async def followers(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select follower_id, created_at from user_follows
                        where followee_id = :id order by created_at desc
                        limit :limit offset :offset
                        """
                    ),
                    {"id": user_id, "limit": limit, "offset": offset},
                )
            ).all()
            return [(row[0], row[1]) for row in rows]

    async def following_list(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[tuple[UUID, datetime]]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select followee_id, created_at from user_follows
                        where follower_id = :id order by created_at desc
                        limit :limit offset :offset
                        """
                    ),
                    {"id": user_id, "limit": limit, "offset": offset},
                )
            ).all()
            return [(row[0], row[1]) for row in rows]

    async def record_activity(
        self, user_id: UUID, event_type: ActivityType, occurred_on: date, goal_id: UUID | None
    ) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    """
                    insert into profile_activity_events (user_id, event_type, occurred_on, goal_id)
                    values (:user_id, :event_type, :occurred_on, :goal_id)
                    on conflict (user_id, event_type, occurred_on, goal_id) do nothing
                    """
                ),
                {
                    "user_id": user_id,
                    "event_type": event_type,
                    "occurred_on": occurred_on,
                    "goal_id": goal_id,
                },
            )

    async def activity_counts(
        self,
        user_id: UUID,
        start: date,
        end: date,
        *,
        public_only: bool = False,
        include_fixtures: bool = False,
    ) -> dict[date, int]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        with owned as (
                          select g.id, g.created_at from goals g
                          where g.user_id = :user_id and g.status = 'active'
                            and (not :public_only or g.visibility = 'public')
                            and (:include_fixtures
                              or not jsonb_exists(g.model_requirements_json, 'workspace_seed'))
                        ),
                        observed as (
                          select distinct e.id, (e.observed_at at time zone 'UTC')::date as day
                          from evidence_events e
                          join goal_evidence ge on ge.evidence_id = e.id
                          join owned o on o.id = ge.goal_id
                          where e.user_id = :user_id and e.status = 'active'
                            and (:include_fixtures or (
                              e.source_quality not in ('demo_fixture', 'synthetic_demo')
                              and coalesce(e.provenance_json->>'event_identity', '')
                                not like 'seed:%'
                            ))
                        ),
                        days as (
                          select a.occurred_on as day from profile_activity_events a
                          where a.user_id = :user_id and a.event_type = 'market_published'
                            and a.goal_id in (select id from owned)
                          union all
                          select (o.created_at at time zone 'UTC')::date from owned o
                          union all
                          select day from observed
                        )
                        select day, count(*)::int as n from days
                        where day between :start and :end
                        group by day
                        """
                    ),
                    {
                        "user_id": user_id,
                        "start": start,
                        "end": end,
                        "public_only": public_only,
                        "include_fixtures": include_fixtures,
                    },
                )
            ).all()
            return {row[0]: int(row[1]) for row in rows}

    async def history_for_goals(self, goal_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        grouped: dict[UUID, list[dict[str, Any]]] = {goal_id: [] for goal_id in goal_ids}
        if not goal_ids:
            return grouped
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select goal_id, probability, created_at, source_kind
                        from market_forecast_history
                        where goal_id in :ids
                        order by created_at
                        """
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": goal_ids},
                )
            ).mappings()
            for row in rows:
                grouped[row["goal_id"]].append(dict(row))
        return grouped

    async def published_updates(self, goal_id: UUID) -> list[dict[str, Any]]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select probability, created_at, source_kind, forecast_status,
                               model_family, model_version,
                               case when receipt_json is null then null else jsonb_build_object(
                                 'normalized_evidence_ids', receipt_json->'normalized_evidence_ids',
                                 'goal_contract_version', receipt_json->'goal_contract_version',
                                 'forecast_spec', jsonb_build_object(
                                   'deadline', receipt_json#>'{forecast_spec,deadline}'
                                 ),
                                 'assumption_names', case
                                   when jsonb_typeof(receipt_json->'assumptions') = 'array' then (
                                     select coalesce(jsonb_agg(item->'name'), '[]'::jsonb)
                                     from jsonb_array_elements(receipt_json->'assumptions') item
                                     where jsonb_typeof(item) = 'object'
                                   )
                                 end
                               ) end as receipt_json
                        from market_forecast_history
                        where goal_id = :id and source_kind = 'published_forecast'
                        order by created_at
                        """
                    ),
                    {"id": goal_id},
                )
            ).mappings()
            return [dict(row) for row in rows]

    async def evidence_metrics(self, goal_id: UUID, evidence_ids: list[str]) -> dict[str, str]:
        if not evidence_ids:
            return {}
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select e.id::text as id, e.metric
                        from evidence_events e
                        join goal_evidence ge on ge.evidence_id = e.id
                        where ge.goal_id = :goal_id and e.id::text in :ids
                        """
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"goal_id": goal_id, "ids": evidence_ids},
                )
            ).mappings()
            return {str(row["id"]): str(row["metric"]) for row in rows}

    async def discover_creators(self, limit: int) -> list[UUID]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        select user_id
                        from goals
                        where visibility = 'public' and status = 'active'
                        group by user_id
                        order by count(*) desc, max(published_at) desc nulls last
                        limit :limit
                        """
                    ),
                    {"limit": limit},
                )
            ).scalars()
            return list(rows)
