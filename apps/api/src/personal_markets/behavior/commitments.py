"""Explicit planned windows and immutable, owner-scoped outcome revisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.behavior.domain import CommitmentTrial
from personal_markets.behavior.tokenize import tokenize
from personal_markets.core.config import get_settings
from personal_markets.core.errors import ResourceNotFoundError, SemanticProviderError
from personal_markets.persistence.database import autocommit_connection, create_engine, transaction

OutcomeStatus = Literal["completed", "partial", "missed", "cancelled", "unknown"]


class Commitment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    goal_id: UUID
    domain: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=160)
    planned_quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=40)
    window_start: datetime
    window_end: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_window(self) -> Commitment:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("Commitment windows need a timezone")
        if self.window_end <= self.window_start:
            raise ValueError("Commitment window must end after it starts")
        return self


class CommitmentObservation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    commitment_id: UUID
    owner_id: UUID
    version: int = Field(ge=1)
    status: OutcomeStatus
    actual_quantity: float | None = Field(default=None, ge=0)
    observed_at: datetime
    confidence: float = Field(default=1, ge=0, le=1)
    source_quality: str = "user_confirmed"
    evidence_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_quantity(self) -> CommitmentObservation:
        if self.status == "completed" and self.actual_quantity is None:
            raise ValueError("Completed commitments require an observed quantity")
        if self.status == "partial" and self.actual_quantity is None:
            raise ValueError("Partial commitments require an observed quantity")
        return self


def trials_from_commitments(
    commitments: list[Commitment], observations: list[CommitmentObservation]
) -> list[CommitmentTrial]:
    latest: dict[UUID, CommitmentObservation] = {}
    for observation in observations:
        previous = latest.get(observation.commitment_id)
        if previous is None or observation.version > previous.version:
            latest[observation.commitment_id] = observation
    trials = []
    for plan in commitments:
        result = latest.get(plan.id)
        if result is None or result.status in {"unknown", "cancelled"}:
            continue
        quantity = result.actual_quantity
        outcome = (
            0.0
            if result.status == "missed"
            else min(1.0, (quantity or 0.0) / plan.planned_quantity)
        )
        trials.append(
            CommitmentTrial(
                trial_id=f"commitment:{plan.id}:v{result.version}",
                user_id=str(plan.owner_id),
                domain=plan.domain,
                action_type=plan.action,
                plan_class="explicit_window",
                planned_amount=plan.planned_quantity,
                realized_amount=quantity,
                unit=plan.unit,
                outcome=outcome,
                observed_at=plan.window_end,
                window_days=(plan.window_end - plan.window_start).total_seconds() / 86400,
                delay_days=max(0.0, (result.observed_at - plan.window_end).total_seconds() / 86400),
                session_key=f"commitment:{plan.id}",
                source="commitment",
                source_quality=result.source_quality,
                tokens=tokenize(plan.domain, plan.action),
            )
        )
    return trials


def validate_outcome(
    plan: Commitment, status: OutcomeStatus, actual_quantity: float | None
) -> None:
    if status == "completed" and (
        actual_quantity is None or actual_quantity < plan.planned_quantity
    ):
        raise SemanticProviderError("Completed quantity must meet the plan")
    if status == "partial" and (
        actual_quantity is None or actual_quantity >= plan.planned_quantity
    ):
        raise SemanticProviderError("Partial quantity must be below the plan")
    if status in {"unknown", "cancelled"} and actual_quantity is not None:
        raise SemanticProviderError("Unknown or cancelled outcomes have no observed quantity")


class InMemoryCommitmentStore:
    def __init__(self) -> None:
        self._plans: dict[UUID, Commitment] = {}
        self._observations: list[CommitmentObservation] = []
        self._lock = asyncio.Lock()

    async def create(self, plan: Commitment) -> Commitment:
        async with self._lock:
            self._plans[plan.id] = plan
            return plan

    async def list_for_goals(
        self, owner_id: UUID, goal_ids: list[UUID]
    ) -> tuple[list[Commitment], list[CommitmentObservation]]:
        plans = [
            p for p in self._plans.values() if p.owner_id == owner_id and p.goal_id in goal_ids
        ]
        ids = {p.id for p in plans}
        return plans, [
            o for o in self._observations if o.owner_id == owner_id and o.commitment_id in ids
        ]

    async def observe(
        self,
        owner_id: UUID,
        commitment_id: UUID,
        *,
        status: OutcomeStatus,
        actual_quantity: float | None,
        observed_at: datetime,
    ) -> CommitmentObservation:
        async with self._lock:
            plan = self._plans.get(commitment_id)
            if plan is None or plan.owner_id != owner_id:
                raise ResourceNotFoundError("Commitment not found")
            validate_outcome(plan, status, actual_quantity)
            version = 1 + max(
                (o.version for o in self._observations if o.commitment_id == commitment_id),
                default=0,
            )
            observation = CommitmentObservation(
                commitment_id=commitment_id,
                owner_id=owner_id,
                version=version,
                status=status,
                actual_quantity=actual_quantity,
                observed_at=observed_at,
            )
            self._observations.append(observation)
            return observation


class PostgresCommitmentStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, plan: Commitment) -> Commitment:
        async with transaction(self._engine) as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                insert into behavior_commitments
                  (id, owner_id, goal_id, domain, action, planned_quantity, unit,
                   window_start, window_end)
                values (:id, :owner_id, :goal_id, :domain, :action, :planned_quantity,
                        :unit, :window_start, :window_end)
                returning *
            """),
                        plan.model_dump(),
                    )
                )
                .mappings()
                .one()
            )
            return Commitment.model_validate(dict(row))

    async def list_for_goals(
        self, owner_id: UUID, goal_ids: list[UUID]
    ) -> tuple[list[Commitment], list[CommitmentObservation]]:
        if not goal_ids:
            return [], []
        async with autocommit_connection(self._engine) as conn:
            plan_rows = (
                (
                    await conn.execute(
                        text("""
                select * from behavior_commitments
                where owner_id = :owner_id and goal_id = any(:goal_ids)
                order by window_start desc
            """),
                        {"owner_id": owner_id, "goal_ids": goal_ids},
                    )
                )
                .mappings()
                .all()
            )
            observation_rows = (
                (
                    await conn.execute(
                        text("""
                select o.* from behavior_commitment_observations o
                join behavior_commitments c on c.id = o.commitment_id
                where c.owner_id = :owner_id and c.goal_id = any(:goal_ids)
                order by o.commitment_id, o.version
            """),
                        {"owner_id": owner_id, "goal_ids": goal_ids},
                    )
                )
                .mappings()
                .all()
            )
        return (
            [Commitment.model_validate(dict(row)) for row in plan_rows],
            [CommitmentObservation.model_validate(dict(row)) for row in observation_rows],
        )

    async def observe(
        self,
        owner_id: UUID,
        commitment_id: UUID,
        *,
        status: OutcomeStatus,
        actual_quantity: float | None,
        observed_at: datetime,
    ) -> CommitmentObservation:
        async with transaction(self._engine) as conn:
            plan_row = (
                (
                    await conn.execute(
                        text("""
                select * from behavior_commitments
                where id = :id and owner_id = :owner_id for update
            """),
                        {"id": commitment_id, "owner_id": owner_id},
                    )
                )
                .mappings()
                .first()
            )
            if plan_row is None:
                raise ResourceNotFoundError("Commitment not found")
            validate_outcome(Commitment.model_validate(dict(plan_row)), status, actual_quantity)
            row = (
                (
                    await conn.execute(
                        text("""
                insert into behavior_commitment_observations
                  (id, commitment_id, owner_id, version, status, actual_quantity,
                   observed_at, confidence, source_quality)
                select :id, :commitment_id, :owner_id,
                  coalesce(max(version), 0) + 1, :status, :actual_quantity,
                  :observed_at, 1, 'user_confirmed'
                from behavior_commitment_observations where commitment_id = :commitment_id
                returning *
            """),
                        {
                            "id": uuid4(),
                            "commitment_id": commitment_id,
                            "owner_id": owner_id,
                            "status": status,
                            "actual_quantity": actual_quantity,
                            "observed_at": observed_at,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return CommitmentObservation.model_validate(dict(row))


@lru_cache
def get_commitment_store() -> InMemoryCommitmentStore | PostgresCommitmentStore:
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresCommitmentStore(create_engine(settings.database_url))
    return InMemoryCommitmentStore()
