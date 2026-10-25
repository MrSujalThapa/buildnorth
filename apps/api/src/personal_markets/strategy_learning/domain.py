"""Typed, unpriced strategy and observed-outcome contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class Decision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    IGNORED = "ignored"


class OutcomeStatus(StrEnum):
    PENDING = "pending"
    SUCCESSFUL = "successful"
    UNSUCCESSFUL = "unsuccessful"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ExpectedOutcome(BaseModel):
    metric: str = Field(min_length=2, max_length=100)
    unit: str = Field(min_length=1, max_length=50)
    direction: str = Field(pattern="^(increase|decrease|maintain)$")
    target: float | None = Field(default=None, allow_inf_nan=False)
    horizon: datetime


class RecommendationDraft(BaseModel):
    strategy_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    action: str = Field(min_length=3, max_length=1000)
    why_now: str = Field(min_length=3, max_length=1000)
    next_step: str = Field(min_length=3, max_length=500)
    evidence_to_collect: str = Field(min_length=3, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    expected: ExpectedOutcome
    grounded_fact_ids: list[str] = Field(default_factory=list, max_length=20)
    external_citations: list[str] = Field(default_factory=list, max_length=10)
    claimed_relationship_ids: list[str] = Field(default_factory=list, max_length=10)


class RecommendationTrial(RecommendationDraft):
    recommendation_id: UUID
    owner_id: UUID
    goal_id: UUID
    milestone_key: str | None = None
    context: dict[str, Any]
    provenance: dict[str, Any]
    proposed_at: datetime
    decision: Decision = Decision.PENDING
    decided_at: datetime | None = None
    population_learning_consented: bool = False


class OutcomeObservation(BaseModel):
    observation_id: UUID
    recommendation_id: UUID
    owner_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    attempted: bool | None = None
    outcome_kind: str = Field(default="intermediate", pattern="^(intermediate|final)$")
    observed_value: float | None = Field(default=None, allow_inf_nan=False)
    status: OutcomeStatus
    observation_confidence: float = Field(ge=0, le=1)
    provenance: dict[str, Any]
    observed_at: datetime
    evidence_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_status(self) -> OutcomeObservation:
        if self.status == OutcomeStatus.SUCCESSFUL and (
            self.attempted is not True or self.observed_value is None or not self.evidence_ids
        ):
            raise ValueError("Successful observations require attempt, value, and linked evidence")
        if self.status == OutcomeStatus.UNSUCCESSFUL and self.attempted is not True:
            raise ValueError("Unsuccessful outcomes require a confirmed attempt")
        return self


class LearningContext(BaseModel):
    goal_id: UUID
    as_of: datetime
    past_trials: list[dict[str, Any]]
    note: str = "Observed association is not evidence that a recommendation caused an outcome."


class BlueprintCandidate(BaseModel):
    """Optional future boundary for reviewed, public marketplace candidates."""

    blueprint_id: str
    strategy_key: str
    summary: str
    review_status: str = Field(pattern="^reviewed$")
    source_ref: str
