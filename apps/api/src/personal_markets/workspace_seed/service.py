"""Seed a user's own workspace with ordinary goals through the normal services.

Every record is owner-scoped and listed in a seed registry so it can be removed
without touching anything the user created. Forecast history is produced by
replaying the observation timeline through the baseline forecasting service at
each evidence date, so every stored point is the model's output for the evidence
available on that day.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_markets.agents.critic import deterministic_critic_decision
from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.behavior.commitments import Commitment
from personal_markets.collections.service import CollectionService
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.inputs_builder import build_numeric_inputs, proposal_from_goal
from personal_markets.forecasting.reprice import _evidence_proposals, _research_ids
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import CriticArtifact, EvidenceEventProposal, GoalArchitectProposal
from personal_markets.workspace_seed.fixtures import (
    ACTIVITY_READINGS,
    MARKETPLACE_ONLY_GOALS,
    SEED_COLLECTIONS,
    SEED_GOALS,
    SEED_VERSION,
    SeedGoal,
    SeedObservation,
)


class SeedRegistry(Protocol):
    async def list(self, owner_id: UUID) -> list[tuple[str, UUID]]: ...

    async def add(self, owner_id: UUID, entity_type: str, entity_id: UUID) -> None: ...


class CommitmentWriter(Protocol):
    async def create(self, plan: Commitment) -> Commitment: ...

    async def observe(
        self,
        owner_id: UUID,
        commitment_id: UUID,
        *,
        status: Any,
        actual_quantity: float | None,
        observed_at: datetime,
    ) -> Any: ...


RETIRED_GOAL = "retired_goal"
RETIRED_COLLECTION = "retired_collection"
RETIRED = {RETIRED_GOAL, RETIRED_COLLECTION}
MAX_GENERATIONS = 64


def seed_goal_id(owner_id: UUID, key: str, generation: int = 0) -> UUID:
    suffix = f":{generation}" if generation else ""
    return uuid5(NAMESPACE_URL, f"playitout:{SEED_VERSION}:{owner_id}:{key}{suffix}")


def _proposal(seed: SeedGoal, now: datetime) -> GoalArchitectProposal:
    payload = dict(seed.proposal)
    payload["deadline"] = (now + timedelta(days=seed.deadline_days)).date().isoformat()
    return refine_architect_proposal(GoalArchitectProposal.model_validate(payload))


def build_seed_goal(
    owner_id: UUID, seed: SeedGoal, now: datetime, generation: int = 0
) -> GoalContract:
    goal = proposal_to_contract(
        _proposal(seed, now), goal_id=seed_goal_id(owner_id, seed.key, generation)
    )
    return goal.model_copy(
        update={
            "model_requirements": {
                **goal.model_requirements,
                "workspace_seed": SEED_VERSION,
                "life_area": seed.domain,
            }
        }
    )


def _event(
    goal_id: UUID, seed: SeedGoal, item: SeedObservation, index: int, now: datetime
) -> EvidenceEventProposal:
    return EvidenceEventProposal(
        event_type=item.event_type,
        domain=item.domain,
        metric=item.metric,
        numeric_value=item.value,
        categorical_value=item.category,
        unit=item.unit,
        observed_at=(now - timedelta(days=item.days_ago)).isoformat(),
        source_type="manual",
        summary=item.summary,
        observation_kind=item.kind,
        event_identity=f"seed:{SEED_VERSION}:{goal_id}:{seed.key}:{index}",
    )


class WorkspaceSeedService:
    def __init__(
        self,
        *,
        goals: GoalService,
        evidence: EvidenceService,
        forecasts: BaselineForecastService,
        collections: CollectionService,
        commitments: CommitmentWriter,
        registry: SeedRegistry,
    ) -> None:
        self._goals = goals
        self._evidence = evidence
        self._forecasts = forecasts
        self._collections = collections
        self._commitments = commitments
        self._registry = registry

    async def status(self, owner_id: UUID) -> dict[str, Any]:
        active = await self._active_records(owner_id)
        counts: dict[str, int] = {}
        for entity_type, _ in active:
            counts[entity_type] = counts.get(entity_type, 0) + 1
        return {"seed_version": SEED_VERSION, "seeded": bool(counts), "records": counts}

    async def seed(
        self,
        owner_id: UUID,
        *,
        now: datetime | None = None,
        keys: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Idempotent: an active seeded goal is left untouched.

        A goal that fails part-way is archived and retired, so a retry rebuilds it under
        the next generation id instead of keeping a half-replayed history. `keys` selects
        a subset of fixtures; by default the user workspace set is seeded.
        """
        clock = now or datetime.now(UTC)
        selected = SEED_GOALS if keys is None else _select_goals(keys)
        rows = await self._registry.list(owner_id)
        registered = {entity_id for _, entity_id in rows}
        active_ids = {goal.goal_id for goal in await self._goals.list_goals(owner_id=owner_id)}
        created: dict[str, UUID] = {}
        summary: list[dict[str, Any]] = []
        for seed in selected:
            generation, goal_id = next(
                (gen, candidate)
                for gen in range(MAX_GENERATIONS)
                for candidate in [seed_goal_id(owner_id, seed.key, gen)]
                if candidate in active_ids or candidate not in registered
            )
            created[seed.key] = goal_id
            if goal_id in active_ids:
                readings = await self._record_activity(owner_id, goal_id, seed, clock)
                summary.append(
                    {
                        "key": seed.key,
                        "goal_id": str(goal_id),
                        "status": "exists",
                        "activity_readings": readings,
                    }
                )
                continue
            goal = await self._goals.create_goal(
                build_seed_goal(owner_id, seed, clock, generation), owner_id
            )
            await self._registry.add(owner_id, "goal", goal.goal_id)
            try:
                await self._record_commitments(owner_id, goal.goal_id, seed, clock)
                points = await self._replay(owner_id, goal, seed, clock)
            except Exception:
                await self._retire_goal(owner_id, goal.goal_id)
                raise
            readings = await self._record_activity(owner_id, goal.goal_id, seed, clock)
            summary.append(
                {
                    "key": seed.key,
                    "goal_id": str(goal.goal_id),
                    "status": "created",
                    "history": points,
                    "activity_readings": readings,
                }
            )
        names = {row.name.casefold() for row in await self._collections.list_for(owner_id)}
        for collection in SEED_COLLECTIONS:
            if collection.name.casefold() in names:
                continue
            if not any(key in created for key in collection.goal_keys):
                continue
            row = await self._collections.create(
                owner_id,
                name=collection.name,
                description=collection.description,
                goal_ids=[created[key] for key in collection.goal_keys if key in created],
            )
            await self._registry.add(owner_id, "collection", row.collection_id)
        return {"seed_version": SEED_VERSION, "goals": summary}

    async def remove(self, owner_id: UUID) -> dict[str, int]:
        """Archive seeded goals and delete seeded collections. Evidence stays immutable."""
        archived = 0
        deleted = 0
        for entity_type, entity_id in await self._active_records(owner_id):
            if entity_type == "goal":
                if await self._retire_goal(owner_id, entity_id):
                    archived += 1
            elif entity_type == "collection":
                try:
                    await self._collections.delete(entity_id, owner_id)
                    deleted += 1
                except ResourceNotFoundError:
                    pass
                await self._registry.add(owner_id, RETIRED_COLLECTION, entity_id)
        return {"archived_goals": archived, "deleted_collections": deleted}

    async def _active_records(self, owner_id: UUID) -> list[tuple[str, UUID]]:
        rows = await self._registry.list(owner_id)
        retired = {entity_id for entity_type, entity_id in rows if entity_type in RETIRED}
        return [
            (entity_type, entity_id)
            for entity_type, entity_id in rows
            if entity_type in {"goal", "collection"} and entity_id not in retired
        ]

    async def _retire_goal(self, owner_id: UUID, goal_id: UUID) -> bool:
        archived = True
        try:
            await self._goals.archive_goal(goal_id, owner_id)
        except ResourceNotFoundError:
            archived = False
        await self._registry.add(owner_id, RETIRED_GOAL, goal_id)
        return archived

    async def _record_commitments(
        self, owner_id: UUID, goal_id: UUID, seed: SeedGoal, now: datetime
    ) -> None:
        for index, item in enumerate(seed.commitments):
            start = now - timedelta(days=item.days_ago)
            end = start + timedelta(days=item.window_days)
            if end > now:
                continue
            plan = await self._commitments.create(
                Commitment(
                    id=uuid5(goal_id, f"commitment:{index}"),
                    owner_id=owner_id,
                    goal_id=goal_id,
                    domain=seed.domain,
                    action=item.action,
                    planned_quantity=item.planned,
                    unit=item.unit,
                    window_start=start,
                    window_end=end,
                    created_at=start,
                )
            )
            await self._commitments.observe(
                owner_id,
                plan.id,
                status=item.status,
                actual_quantity=item.actual,
                observed_at=end + timedelta(days=item.resolved_late_days),
            )

    async def _record_activity(
        self, owner_id: UUID, goal_id: UUID, seed: SeedGoal, now: datetime
    ) -> int:
        """Commit current activity readings; identities are per seed day, so retries dedupe."""
        readings = ACTIVITY_READINGS.get(seed.key, ())
        if not readings:
            return 0
        prefix = f"seed:{SEED_VERSION}:{goal_id}:{seed.key}:activity:{now.date().isoformat()}"
        events = [
            _event(goal_id, seed, item, index, now).model_copy(
                update={"event_identity": f"{prefix}:{index}"}
            )
            for index, item in enumerate(readings)
        ]
        await self._evidence.commit(owner_id, goal_id, events, None, [])
        return len(events)

    async def _replay(
        self, owner_id: UUID, goal: GoalContract, seed: SeedGoal, now: datetime
    ) -> list[dict[str, Any]]:
        """Commit evidence in date order and publish the model's forecast at each step."""
        ordered = sorted(enumerate(seed.observations), key=lambda pair: -pair[1].days_ago)
        batches: dict[float, list[tuple[int, SeedObservation]]] = {}
        for index, item in ordered:
            batches.setdefault(item.days_ago, []).append((index, item))
        proposal = proposal_from_goal(goal)
        points: list[dict[str, Any]] = []
        for days_ago, batch in batches.items():
            moment = now - timedelta(days=days_ago)
            await self._evidence.commit(
                owner_id,
                goal.goal_id,
                [_event(goal.goal_id, seed, item, index, now) for index, item in batch],
                None,
                [],
            )
            events = await self._evidence.list_for_goal(goal.goal_id)
            visible = [item for item in events if _observed_by(item, moment)]
            status, probability = await self._publish(owner_id, goal, proposal, visible, moment)
            points.append(
                {"as_of": moment.isoformat(), "status": status, "probability": probability}
            )
        return points

    async def _publish(
        self,
        owner_id: UUID,
        goal: GoalContract,
        proposal: GoalArchitectProposal,
        events: Sequence[NormalizedEvidence],
        moment: datetime,
    ) -> tuple[str, float | None]:
        rows = list(events)
        evidence_ids = [str(item.evidence_id) for item in rows if item.evidence_id]
        numeric = build_numeric_inputs(goal, proposal, rows, now=moment)
        pricing = self._forecasts.compute(
            goal, proposal, evidence_ids, {}, _research_ids(goal, proposal, numeric), numeric
        )
        if not pricing.priced or pricing.raw_probability is None:
            return "not_priced", None
        pricing = pricing.model_copy(
            update={"receipt": {**pricing.receipt, "evaluated_as_of": moment.isoformat()}}
        )
        issues = self._forecasts.deterministic_issues(
            _evidence_proposals(rows), evidence_ids, pricing
        )
        critic = deterministic_critic_decision(issues, pricing) or CriticArtifact(
            decision="publish", issues=[], limitations=pricing.limitations, required_actions=[]
        )
        status = await self._forecasts.publish(goal, pricing, critic, published_at=moment)
        await self._goals.record_publication(goal.goal_id, owner_id, critic, status)
        return status, pricing.raw_probability


def _select_goals(keys: Sequence[str]) -> tuple[SeedGoal, ...]:
    catalog = {seed.key: seed for seed in (*SEED_GOALS, *MARKETPLACE_ONLY_GOALS)}
    unknown = [key for key in keys if key not in catalog]
    if unknown:
        raise ValueError(f"unknown seed goal keys: {', '.join(unknown)}")
    return tuple(catalog[key] for key in keys)


def _observed_by(item: NormalizedEvidence, moment: datetime) -> bool:
    if item.observed_at is None:
        return False
    stamp = item.observed_at if item.observed_at.tzinfo else item.observed_at.replace(tzinfo=UTC)
    return stamp <= moment + timedelta(seconds=1)
