"""Trusted, owner-scoped current goal context from existing evidence rows."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.goals.domain import GoalContract
from personal_markets.persistence.database import autocommit_connection
from personal_markets.strategy_learning.service import GroundedFact, RecommendationContext


class PostgresGoalContextSource:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def build(
        self, owner_id: UUID, goal: GoalContract, as_of: datetime
    ) -> RecommendationContext:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                select e.id, e.metric, e.numeric_value, e.categorical_value, e.unit,
                  e.observed_at, e.created_at, e.source_quality
                from evidence_events e
                join goal_evidence ge on ge.evidence_id=e.id and ge.goal_id=:goal
                join goals g on g.id=ge.goal_id and g.user_id=:owner
                where e.user_id=:owner and e.status='active'
                  and e.observed_at<=:as_of and e.created_at<=:as_of
                  and coalesce(e.provenance_json->>'event_identity','') not like 'seed:%'
                  and not exists (
                    select 1 from goal_evidence seeded_link
                    join workspace_seed_records seed
                      on seed.entity_id=seeded_link.goal_id and seed.owner_id=:owner
                     and seed.entity_type='goal'
                    where seeded_link.evidence_id=e.id
                  )
                order by e.observed_at desc, e.created_at desc limit 20
            """),
                        {"owner": owner_id, "goal": goal.goal_id, "as_of": as_of},
                    )
                )
                .mappings()
                .all()
            )
        facts = []
        observations = []
        observed_metrics = set()
        for row in rows:
            value = (
                row["numeric_value"]
                if row["numeric_value"] is not None
                else row["categorical_value"]
            )
            unit = row["unit"] or ""
            summary = f"{row['metric']}: {value} {unit}".strip()
            facts.append(
                GroundedFact(
                    fact_id=f"evidence:{row['id']}",
                    statement=summary,
                    observed_at=row["observed_at"],
                    available_at=row["created_at"],
                    provenance=f"evidence:{row['id']} ({row['source_quality']})",
                    kind="evidence",
                )
            )
            observations.append(
                {
                    "metric": row["metric"],
                    "value": value,
                    "unit": unit,
                    "observed_at": row["observed_at"].isoformat(),
                    "evidence_id": str(row["id"]),
                }
            )
            observed_metrics.add(str(row["metric"]).casefold())
        gaps = [
            f"No direct metric record for {dimension}"
            for dimension in goal.state_dimensions
            if dimension.casefold() not in observed_metrics
        ]
        constraints = []
        if goal.resource_constraints.hours_per_week is not None:
            constraints.append(
                f"Time budget: {goal.resource_constraints.hours_per_week} hours/week"
            )
        if goal.resource_constraints.budget_amount is not None:
            constraints.append(
                f"Budget: {goal.resource_constraints.budget_amount} "
                f"{goal.resource_constraints.budget_currency}"
            )
        return RecommendationContext(
            facts=facts,
            progress={"recent_observations": observations},
            evidence_gaps=gaps,
            user_constraints=constraints,
            as_of=as_of,
        )
