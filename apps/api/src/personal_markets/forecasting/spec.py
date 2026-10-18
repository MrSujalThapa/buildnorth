"""Declarative contract for the existing five model families, not a generic compiler."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.goals.domain import GoalContract


class ForecastSpec(BaseModel):
    spec_version: Literal[1] = 1
    goal_id: UUID
    goal_contract_version: int
    outcome: dict[str, str]
    deadline: datetime
    units: str | None
    family: str
    model_version: str
    required_state: list[str]
    required_parameters: list[str]
    parameter_provenance: list[dict[str, Any]] = Field(default_factory=list)
    research_required: bool = False
    research_questions: list[str] = Field(default_factory=list)
    status: Literal["NEEDS_INPUT", "READY", "INSUFFICIENT_EVIDENCE"] = "NEEDS_INPUT"
    limitations: list[str] = Field(default_factory=list)


def compile_existing_spec(goal: GoalContract, inputs: NumericInputs | None = None) -> ForecastSpec:
    descriptor = ForecastModelRegistry().select_for(goal, inputs).descriptor
    existing = goal.model_requirements.get("forecast_spec") or {}
    return ForecastSpec(
        goal_id=goal.goal_id,
        goal_contract_version=goal.version,
        outcome={str(k): str(v) for k, v in goal.success_definition.items()},
        deadline=goal.deadline,
        units=existing.get("units"),
        family=descriptor.family,
        model_version=descriptor.version,
        required_state=list(descriptor.required_state),
        required_parameters=list(descriptor.required_assumptions),
        research_required=bool(existing.get("research_required")),
        research_questions=list(existing.get("research_questions") or []),
        limitations=[
            *descriptor.extrapolation_limits,
            "Family compatibility does not imply priceability or empirical calibration.",
        ],
    )
