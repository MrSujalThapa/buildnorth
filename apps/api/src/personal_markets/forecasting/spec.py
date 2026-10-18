"""Declarative forecast specification.

Version 1 remains a snapshot of the five existing families. Version 2 adds a
validated primitive composition. Both are serializable; v1 receipts still load.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.goals.domain import GoalContract


class ForecastSpec(BaseModel):
    spec_version: Literal[1, 2] = 1
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
    compiler_version: str | None = None
    owner_id: str | None = None
    primitives: list[dict[str, Any]] = Field(default_factory=list)
    composition: dict[str, Any] | None = None
    observable_inputs: list[dict[str, Any]] = Field(default_factory=list)
    unpriced_reasons: list[str] = Field(default_factory=list)
    population: str | None = None
    validation_requirements: list[str] = Field(default_factory=list)


def compile_existing_spec(goal: GoalContract, inputs: NumericInputs | None = None) -> ForecastSpec:
    existing = goal.model_requirements.get("forecast_spec") or {}
    if int(existing.get("spec_version") or 1) == 2 and existing.get("primitives"):
        raw_outcome = existing.get("outcome") or {}
        outcome = (
            {str(key): str(value) for key, value in raw_outcome.items() if value is not None}
            if isinstance(raw_outcome, dict)
            else {str(k): str(v) for k, v in goal.success_definition.items()}
        )
        payload = {
            **existing,
            "spec_version": 2,
            "goal_id": str(goal.goal_id),
            "goal_contract_version": goal.version,
            "deadline": existing.get("deadline") or goal.deadline,
            "outcome": outcome,
        }
        return ForecastSpec.model_validate(payload)
    descriptor = ForecastModelRegistry().select_for(goal, inputs).descriptor
    return ForecastSpec(
        spec_version=1,
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
        compiler_version="existing_v1",
        primitives=list(existing.get("primitives") or []),
        composition=existing.get("composition"),
        parameter_provenance=list(existing.get("parameter_provenance") or []),
        unpriced_reasons=list(existing.get("unpriced_reasons") or []),
        population=existing.get("population"),
    )
