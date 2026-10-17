from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class GoalType(StrEnum):
    DEADLINE_EVENT = "deadline_event"
    THRESHOLD = "threshold"
    CONTINUOUS_TARGET = "continuous_target"
    HABIT = "habit"
    MULTI_OUTCOME = "multi_outcome"


class ForecastStatus(StrEnum):
    CALIBRATED = "CALIBRATED"
    ANCHORED = "ANCHORED"
    EXPLORATORY = "EXPLORATORY"


class ResourceConstraints(BaseModel):
    hours_per_week: float | None = Field(default=None, gt=0)
    budget_amount: float | None = Field(default=None, ge=0)
    budget_currency: str | None = None

    @model_validator(mode="after")
    def require_currency_with_budget(self) -> "ResourceConstraints":
        if self.budget_amount is not None and not self.budget_currency:
            raise ValueError("budget_currency is required when budget_amount is set")
        return self


class GoalContract(BaseModel):
    goal_id: UUID
    title: str = Field(min_length=3, max_length=200)
    goal_type: GoalType
    success_definition: dict[str, Any]
    deadline: datetime
    target_probability: float | None = Field(default=None, ge=0, le=1)
    resource_constraints: ResourceConstraints = Field(default_factory=ResourceConstraints)
    state_dimensions: list[str] = Field(min_length=1)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    forecast_status: ForecastStatus = ForecastStatus.EXPLORATORY
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_forecast_readiness(self) -> "GoalContract":
        if not self.success_definition:
            raise ValueError("success_definition must be measurable and non-empty")
        if self.deadline <= datetime.now(UTC):
            raise ValueError("deadline must be in the future")
        if len(set(self.state_dimensions)) != len(self.state_dimensions):
            raise ValueError("state_dimensions must be unique")
        return self
