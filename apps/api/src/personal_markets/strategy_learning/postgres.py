"""PostgreSQL strategy-learning adapter. Every read and mutation scopes the owner."""

from __future__ import annotations

import json
import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.strategy_learning.domain import (
    Decision,
    ExpectedOutcome,
    OutcomeObservation,
    OutcomeStatus,
    RecommendationTrial,
)


class PostgresStrategyLearningRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    def _trial(row: dict[str, object]) -> RecommendationTrial:
        context = row["context_json"]
        assert isinstance(context, dict)
        return RecommendationTrial.model_validate(
            {
                "recommendation_id": row["id"],
                "owner_id": row["owner_id"],
                "goal_id": row["goal_id"],
                "milestone_key": row["milestone_key"],
                "strategy_key": row["strategy_key"],
                "action": row["action"],
                "why_now": row["rationale"],
                "next_step": row["next_step"],
                "evidence_to_collect": row["evidence_to_collect"],
                "assumptions": row["assumptions_json"],
                "context": context,
                "grounded_fact_ids": context.get("grounded_fact_ids", []),
                "external_citations": context.get("external_citations", []),
                "claimed_relationship_ids": context.get("claimed_relationship_ids", []),
                "expected": ExpectedOutcome.model_validate(
                    {
                        "metric": row["expected_metric"],
                        "unit": row["expected_unit"],
                        "direction": row["expected_direction"],
                        "target": row["expected_target"],
                        "horizon": row["evaluation_horizon"],
                    }
                ),
                "provenance": row["provenance_json"],
                "proposed_at": row["proposed_at"],
                "decision": row["decision"],
                "decided_at": row["decided_at"],
                "population_learning_consented": row["population_learning_consented"],
            }
        )

    async def create(self, trial: RecommendationTrial, fingerprint: str) -> RecommendationTrial:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                insert into strategy_recommendations (
                  id, owner_id, goal_id, milestone_key, strategy_key, action, rationale,
                  next_step, evidence_to_collect, context_json, assumptions_json, provenance_json,
                  expected_metric, expected_unit, expected_direction, expected_target,
                  evaluation_horizon, proposed_at, fingerprint, population_learning_consented
                ) values (
                  :id, :owner, :goal, :milestone, :strategy, :action, :why,
                  :next_step, :collect, cast(:context as jsonb), cast(:assumptions as jsonb),
                  cast(:provenance as jsonb), :metric, :unit, :direction, :target,
                  :horizon, :proposed, :fingerprint, :consent
                ) on conflict (owner_id, goal_id, fingerprint) do nothing
                returning *
            """),
                        {
                            "id": trial.recommendation_id,
                            "owner": trial.owner_id,
                            "goal": trial.goal_id,
                            "milestone": trial.milestone_key,
                            "strategy": trial.strategy_key,
                            "action": trial.action,
                            "why": trial.why_now,
                            "next_step": trial.next_step,
                            "collect": trial.evidence_to_collect,
                            "context": json.dumps(trial.context),
                            "assumptions": json.dumps(trial.assumptions),
                            "provenance": json.dumps(trial.provenance),
                            "metric": trial.expected.metric,
                            "unit": trial.expected.unit,
                            "direction": trial.expected.direction,
                            "target": trial.expected.target,
                            "horizon": trial.expected.horizon,
                            "proposed": trial.proposed_at,
                            "fingerprint": fingerprint,
                            "consent": trial.population_learning_consented,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = (
                    (
                        await connection.execute(
                            text("""
                        select * from strategy_recommendations
                        where owner_id=:owner and goal_id=:goal and fingerprint=:fingerprint
                    """),
                            {
                                "owner": trial.owner_id,
                                "goal": trial.goal_id,
                                "fingerprint": fingerprint,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
        return self._trial(dict(row))

    async def get(self, owner_id: UUID, trial_id: UUID) -> RecommendationTrial | None:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                select * from strategy_recommendations where id=:id and owner_id=:owner
            """),
                        {"id": trial_id, "owner": owner_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._trial(dict(row)) if row else None

    async def decide(
        self, owner_id: UUID, trial_id: UUID, decision: Decision, at: datetime
    ) -> RecommendationTrial:
        if decision == Decision.PENDING:
            raise ValueError("A feedback decision must resolve pending")
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                update strategy_recommendations set decision=:decision, decided_at=:at
                where id=:id and owner_id=:owner and decision='pending' and proposed_at<=:at
                returning *
            """),
                        {"id": trial_id, "owner": owner_id, "decision": decision, "at": at},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row:
            return self._trial(dict(row))
        existing = await self.get(owner_id, trial_id)
        if existing is not None and existing.decision == decision:
            return existing
        raise ValueError("Recommendation is absent or already has different feedback")

    async def observe(self, observation: OutcomeObservation, goal_id: UUID) -> OutcomeObservation:
        async with transaction(self._engine) as connection:
            trial = (
                (
                    await connection.execute(
                        text("""
                select id, goal_id, proposed_at, expected_metric, expected_unit
                from strategy_recommendations
                where id=:id and owner_id=:owner for update
            """),
                        {"id": observation.recommendation_id, "owner": observation.owner_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if trial is None or trial["goal_id"] != goal_id:
                raise ValueError("Recommendation is not owned by this goal")
            if observation.observed_at < trial["proposed_at"]:
                raise ValueError("An outcome cannot precede its recommendation")
            if observation.evidence_ids:
                rows = (
                    (
                        await connection.execute(
                            text("""
                    select e.id, e.metric, e.unit, e.numeric_value,
                      e.provenance_json->>'observation_kind' as observation_kind,
                      e.provenance_json->>'verification_status' as verification_status
                    from evidence_events e
                    join goal_evidence ge on ge.evidence_id=e.id and ge.goal_id=:goal
                    where e.id=any(:ids) and e.user_id=:owner and e.status='active'
                      and e.observed_at>=:proposed and e.observed_at<=:observed
                      and e.created_at<=:observed
                      and not exists (select 1 from workspace_seed_records s
                        where s.owner_id=:owner and s.entity_type='evidence'
                          and s.entity_id=e.id)
                      and coalesce(e.provenance_json->>'event_identity','') not like 'seed:%'
                      and not exists (
                        select 1 from goal_evidence seeded_link
                        join workspace_seed_records seeded_goal
                          on seeded_goal.entity_id=seeded_link.goal_id
                         and seeded_goal.owner_id=:owner
                         and seeded_goal.entity_type='goal'
                        where seeded_link.evidence_id=e.id
                      )
                """),
                            {
                                "ids": observation.evidence_ids,
                                "goal": goal_id,
                                "owner": observation.owner_id,
                                "observed": observation.observed_at,
                                "proposed": trial["proposed_at"],
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
                if {row["id"] for row in rows} != set(observation.evidence_ids):
                    raise ValueError(
                        "Evidence is missing, synthetic, future dated, or outside goal scope"
                    )
                if observation.status in {
                    OutcomeStatus.SUCCESSFUL,
                    OutcomeStatus.UNSUCCESSFUL,
                } and not any(
                    row["metric"] == trial["expected_metric"]
                    and row["unit"] == trial["expected_unit"]
                    and row["observation_kind"] == "snapshot"
                    and (
                        observation.outcome_kind != "final"
                        or row["verification_status"] == "verified_outcome"
                    )
                    and row["numeric_value"] is not None
                    and observation.observed_value is not None
                    and math.isclose(
                        row["numeric_value"],
                        observation.observed_value,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                    for row in rows
                ):
                    raise ValueError(
                        "Outcome needs a matching direct metric snapshot"
                        " (and verified provenance for a final outcome)"
                    )
            row = (
                (
                    await connection.execute(
                        text("""
                insert into strategy_outcome_observations (
                  id, recommendation_id, owner_id, idempotency_key, attempted,
                  outcome_kind, observed_value,
                  status, observation_confidence, provenance_json, observed_at
                ) values (:id,:recommendation,:owner,:key,:attempted,:kind,:value,
                  :status,:confidence,
                  cast(:provenance as jsonb),:observed)
                on conflict (recommendation_id,idempotency_key) do nothing
                returning *
            """),
                        {
                            "id": observation.observation_id,
                            "recommendation": observation.recommendation_id,
                            "owner": observation.owner_id,
                            "key": observation.idempotency_key,
                            "attempted": observation.attempted,
                            "value": observation.observed_value,
                            "kind": observation.outcome_kind,
                            "status": observation.status,
                            "confidence": observation.observation_confidence,
                            "provenance": json.dumps(observation.provenance),
                            "observed": observation.observed_at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = (
                    (
                        await connection.execute(
                            text("""
                    select * from strategy_outcome_observations
                    where recommendation_id=:recommendation and idempotency_key=:key
                      and owner_id=:owner
                """),
                            {
                                "recommendation": observation.recommendation_id,
                                "key": observation.idempotency_key,
                                "owner": observation.owner_id,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            stored_id = row["id"]
            existing_ids = (
                (
                    await connection.execute(
                        text("""
                select evidence_id from strategy_outcome_evidence where observation_id=:id
            """),
                        {"id": stored_id},
                    )
                )
                .scalars()
                .all()
            )
            if stored_id != observation.observation_id and (
                row["attempted"] != observation.attempted
                or row["outcome_kind"] != observation.outcome_kind
                or row["observed_value"] != observation.observed_value
                or row["status"] != observation.status
                or row["observed_at"] != observation.observed_at
                or set(existing_ids) != set(observation.evidence_ids)
            ):
                raise ValueError("An idempotency key cannot refer to a different outcome")
            for evidence_id in observation.evidence_ids:
                await connection.execute(
                    text("""
                    insert into strategy_outcome_evidence
                      (observation_id,owner_id,goal_id,evidence_id)
                    values (:id,:owner,:goal,:evidence) on conflict do nothing
                """),
                    {
                        "id": stored_id,
                        "owner": observation.owner_id,
                        "goal": goal_id,
                        "evidence": evidence_id,
                    },
                )
        return observation.model_copy(update={"observation_id": stored_id})

    async def history(
        self, owner_id: UUID, goal_id: UUID, as_of: datetime, *, include_synthetic: bool = False
    ) -> list[tuple[RecommendationTrial, OutcomeObservation | None]]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                select r.*, o.id as outcome_id, o.idempotency_key as outcome_key,
                  o.attempted, o.outcome_kind, o.observed_value, o.status as outcome_status,
                  o.observation_confidence, o.provenance_json as outcome_provenance,
                  o.observed_at as outcome_at,
                  coalesce(l.evidence_ids, '{}'::uuid[]) as evidence_ids,
                  l.evidence_active
                from strategy_recommendations r
                left join lateral (
                  select * from strategy_outcome_observations
                  where recommendation_id=r.id and owner_id=:owner
                    and observed_at<=:as_of and created_at<=:as_of
                  order by observed_at desc, created_at desc, id desc limit 1
                ) o on true
                left join lateral (
                  select array_agg(link.evidence_id) as evidence_ids,
                    bool_and(e.status='active') as evidence_active
                  from strategy_outcome_evidence link
                  join evidence_events e on e.id=link.evidence_id
                  where link.observation_id=o.id
                ) l on true
                where r.owner_id=:owner and r.goal_id=:goal
                  and r.proposed_at<=:as_of and r.created_at<=:as_of
                  and (:include_synthetic or not exists (
                    select 1 from workspace_seed_records s
                    where s.owner_id=:owner and s.entity_type='goal' and s.entity_id=r.goal_id
                  ))
                  and (:include_synthetic or not exists (
                    select 1 from goals g where g.id=r.goal_id
                      and jsonb_exists(g.model_requirements_json, 'workspace_seed')
                  ))
                order by r.proposed_at desc, r.id desc limit 30
            """),
                        {
                            "owner": owner_id,
                            "goal": goal_id,
                            "as_of": as_of,
                            "include_synthetic": include_synthetic,
                        },
                    )
                )
                .mappings()
                .all()
            )
        result = []
        for raw in rows:
            row = dict(raw)
            outcome = None
            if row["outcome_id"] is not None:
                effective_status = row["outcome_status"]
                provenance = dict(row["outcome_provenance"])
                if row["evidence_active"] is False and effective_status in {
                    OutcomeStatus.SUCCESSFUL,
                    OutcomeStatus.UNSUCCESSFUL,
                }:
                    effective_status = OutcomeStatus.INCONCLUSIVE
                    provenance["current_evidence_status"] = "retracted"
                outcome = OutcomeObservation(
                    observation_id=row["outcome_id"],
                    recommendation_id=row["id"],
                    owner_id=owner_id,
                    idempotency_key=row["outcome_key"],
                    attempted=row["attempted"],
                    observed_value=row["observed_value"],
                    outcome_kind=row["outcome_kind"],
                    status=effective_status,
                    observation_confidence=row["observation_confidence"],
                    provenance=provenance,
                    observed_at=row["outcome_at"],
                    evidence_ids=list(row["evidence_ids"]),
                )
            result.append((self._trial(row), outcome))
        return result
