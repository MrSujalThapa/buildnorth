from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low", "insufficient"]
DimensionKey = Literal[
    "follow_through",
    "consistency",
    "commitment_realism",
    "momentum",
    "reliability",
    "recovery",
    "evidence_quality",
    "goal_relevance",
]
ExecutionSource = Literal["FITTED", "PRIOR", "USER_ASSUMPTION", "EXPLORATION_ASSUMPTION"]


class CommitmentTrial(BaseModel):
    """One scored planned-vs-observed window. Not a personality score."""

    trial_id: str
    user_id: str = "default"
    domain: str = "general"
    action_type: str = "unspecified"
    plan_class: str = "commitment"
    planned_amount: float | None = None
    realized_amount: float | None = None
    unit: str | None = None
    outcome: float = Field(ge=0, le=1)
    observed_at: datetime
    window_days: float = 1.0
    delay_days: float | None = None
    session_key: str
    source: str = "manual"
    source_quality: str = "user_entered"
    event_count: int = 1
    tokens: list[str] = Field(default_factory=list)


class ActionContext(BaseModel):
    action_type: str = "unspecified"
    domain: str = "general"
    planned_amount: float | None = None
    unit: str | None = None
    tokens: list[str] = Field(default_factory=list)
    description: str = ""


class HierarchicalPosterior(BaseModel):
    mean: float
    n_eff: float
    alpha: float
    beta: float
    half_life_days: float
    scope: str


class ExecutionEstimate(BaseModel):
    probability: float = Field(ge=0, le=1)
    interval: tuple[float, float]
    n_eff: float
    n_raw: int
    confidence: Confidence
    source: ExecutionSource
    half_life_days: float
    global_mean: float
    domain_mean: float
    action_mean: float
    usable: bool
    notes: list[str] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)


class DimensionProvenance(BaseModel):
    comparable_commitments: int
    completed: float
    recency_weighted_completion: float | None = None
    evidence_window_days: float | None = None
    sources: list[str] = Field(default_factory=list)
    n_eff: float
    formula: str
    details: list[str] = Field(default_factory=list)


class BehaviorDimension(BaseModel):
    key: DimensionKey
    label: str
    value: float | None = Field(default=None, ge=0, le=1)
    display_percent: int | None = None
    limited_evidence: bool = True
    confidence: Confidence = "insufficient"
    provenance: DimensionProvenance


class BehaviorProfile(BaseModel):
    """Display + audit artifact. Polygon area is not a score."""

    estimator_version: str
    as_of: datetime
    execution: ExecutionEstimate
    dimensions: list[BehaviorDimension]
    disclaimer: str = (
        "This summarizes observed follow-through, not personality. "
        "The radar is a visual summary; pricing uses the execution model."
    )
    evidence_sufficiency: Confidence
    n_raw: int
    n_eff: float
