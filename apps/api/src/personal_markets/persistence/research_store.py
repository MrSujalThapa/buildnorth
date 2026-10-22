from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.ports import ResearchArtifact


class ResearchStore:
    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine
        self._rows: dict[tuple[UUID, UUID, UUID], dict[str, Any]] = {}

    async def save(self, owner: UUID, goal: UUID, run: UUID, artifact: ResearchArtifact) -> None:
        payload = artifact.model_dump(mode="json")
        if self._engine is None:
            self._rows[owner, goal, run] = payload
            return
        async with transaction(self._engine) as conn:
            await conn.execute(
                text("""
                insert into goal_research_artifacts (id, user_id, goal_id, artifact_json)
                select :id, :owner, :goal, cast(:payload as jsonb)
                where exists (select 1 from goals where id=:goal and user_id=:owner)
                on conflict (id) do nothing
            """),
                {"id": run, "owner": owner, "goal": goal, "payload": json.dumps(payload)},
            )

    async def list_for_goal(self, owner: UUID, goal: UUID) -> list[dict[str, Any]]:
        if self._engine is None:
            return [
                row
                for (user_id, goal_id, _), row in self._rows.items()
                if user_id == owner and goal_id == goal
            ]
        async with autocommit_connection(self._engine) as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                select artifact_json from goal_research_artifacts
                where user_id=:owner and goal_id=:goal order by created_at
            """),
                        {"owner": owner, "goal": goal},
                    )
                )
                .mappings()
                .all()
            )
        return [row["artifact_json"] for row in rows]
