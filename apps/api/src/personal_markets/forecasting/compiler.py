"""Validate a typed ForecastSpec against the registered primitive library.

The LLM may propose a spec. This module is the only path that can accept it.
It cannot execute Python, formulas, or unrestricted distributions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from personal_markets.forecasting.primitives import COMPILER_VERSION, REGISTERED_PRIMITIVES
from personal_markets.goals.domain import GoalContract

PrimitiveKind = Literal[
    "deadline_hazard",
    "funnel",
    "cumulative_count",
    "growth",
    "continuous_threshold",
    "habit",
    "dependency_dag",
    "financial",
]
JoinKind = Literal["single", "sequential_and", "funnel"]
IndependenceKind = Literal["assumed_independent", "correlated", "unspecified"]


class OutcomeSpec(BaseModel):
    predicate: Literal["metric_at_least", "metric_at_most", "event_by_deadline", "habit_rate"]
    metric: str
    threshold: float | None = None
    units: str | None = None
    event: str | None = None


class ObservableInput(BaseModel):
    metric: str
    unit: str | None = None
    kind: Literal["snapshot", "increment", "period", "rate", "continuous", "categorical"] = (
        "snapshot"
    )
    required: bool = True
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


class PrimitiveNode(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    kind: PrimitiveKind
    metric: str
    unit: str | None = None
    state_bindings: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, float] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    independence: IndependenceKind = "unspecified"
    prerequisites: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_token(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.replace("_", "").isalnum():
            raise ValueError("primitive id must be alphanumeric")
        return cleaned


class CompositionGraph(BaseModel):
    join: JoinKind = "single"
    nodes: list[str] = Field(default_factory=list)
    correlation: Literal["independent", "shared_factor", "unspecified"] = "unspecified"


class ForecastSpecV2(BaseModel):
    spec_version: Literal[2] = 2
    compiler_version: str = COMPILER_VERSION
    goal_id: UUID
    owner_id: UUID | None = None
    goal_contract_version: int = 1
    outcome: OutcomeSpec
    deadline: datetime
    units: str | None = None
    family: str
    model_version: str
    primitives: list[PrimitiveNode]
    composition: CompositionGraph
    required_state: list[str] = Field(default_factory=list)
    required_parameters: list[str] = Field(default_factory=list)
    observable_inputs: list[ObservableInput] = Field(default_factory=list)
    parameter_provenance: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    population: str | None = None
    research_required: bool = False
    research_questions: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)
    unpriced_reasons: list[str] = Field(default_factory=list)
    status: Literal["NEEDS_INPUT", "READY", "INSUFFICIENT_EVIDENCE"] = "NEEDS_INPUT"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _graph_matches_nodes(self) -> ForecastSpecV2:
        ids = [node.id for node in self.primitives]
        if len(ids) != len(set(ids)):
            raise ValueError("primitive ids must be unique")
        if self.composition.nodes and set(self.composition.nodes) - set(ids):
            raise ValueError("composition nodes must refer to declared primitives")
        for node in self.primitives:
            if node.kind not in REGISTERED_PRIMITIVES:
                raise ValueError(f"unregistered primitive {node.kind}")
            unknown = [item for item in node.prerequisites if item not in ids]
            if unknown:
                raise ValueError(f"unknown prerequisite {unknown}")
        return self


class CompileResult(BaseModel):
    accepted: bool
    spec: ForecastSpecV2 | None = None
    reasons: list[str] = Field(default_factory=list)


_FORBIDDEN_CONFIG_KEYS = frozenset(
    {"python", "code", "eval", "exec", "formula", "expression", "sql", "module"}
)
_ALLOWED_GROWTH = frozenset({"loglinear", "logistic"})
_ALLOWED_COUNT = frozenset({"poisson", "negbin"})
_ALLOWED_TIME = frozenset({"day", "week", "month"})


def validate_primitive_config(node: PrimitiveNode) -> list[str]:
    errors: list[str] = []
    if _FORBIDDEN_CONFIG_KEYS.intersection(node.config):
        errors.append(f"{node.id}: arbitrary code/formula config is not allowed")
    kind = node.kind
    process = str(node.config.get("process", ""))
    if kind == "growth" and process and process not in _ALLOWED_GROWTH:
        errors.append(f"{node.id}: growth process must be loglinear or logistic")
    if kind == "cumulative_count" and process and process not in _ALLOWED_COUNT:
        errors.append(f"{node.id}: count process must be poisson or negbin")
    time_unit = str(node.config.get("time_unit", "week"))
    if time_unit not in _ALLOWED_TIME:
        errors.append(f"{node.id}: time_unit must be day, week, or month")
    if kind == "funnel":
        stages = node.config.get("stages")
        if not isinstance(stages, list) or len(stages) < 2:
            errors.append(f"{node.id}: funnel requires at least two named stages")
    if kind == "dependency_dag":
        durations = node.config.get("nodes")
        if durations is not None and not isinstance(durations, list):
            errors.append(f"{node.id}: DAG nodes must be a list")
    if kind == "habit":
        prior_a = node.parameters.get("prior_alpha", 1.0)
        prior_b = node.parameters.get("prior_beta", 1.0)
        if prior_a <= 0 or prior_b <= 0:
            errors.append(f"{node.id}: Beta priors must be positive")
    return errors


def compile_spec(spec: ForecastSpecV2) -> CompileResult:
    reasons: list[str] = []
    if spec.compiler_version != COMPILER_VERSION:
        reasons.append(f"unsupported compiler_version {spec.compiler_version}")
    if not spec.primitives:
        reasons.append("spec declares no primitives")
    if spec.composition.join == "single" and len(spec.primitives) != 1:
        reasons.append("single join requires exactly one primitive")
    if (
        spec.outcome.predicate in {"metric_at_least", "metric_at_most"}
        and spec.outcome.threshold is None
    ):
        reasons.append("threshold outcome needs a numeric threshold")
    for node in spec.primitives:
        reasons.extend(validate_primitive_config(node))
    if reasons:
        return CompileResult(accepted=False, reasons=reasons)
    return CompileResult(accepted=True, spec=spec)


def spec_from_mapping(payload: dict[str, Any] | None) -> ForecastSpecV2 | None:
    if not payload or int(payload.get("spec_version") or 1) != 2:
        return None
    if not payload.get("primitives"):
        return None
    try:
        spec = ForecastSpecV2.model_validate(payload)
    except Exception:
        return None
    result = compile_spec(spec)
    return result.spec if result.accepted else None


def goal_spec(goal: GoalContract) -> ForecastSpecV2 | None:
    payload = goal.model_requirements.get("forecast_spec")
    if isinstance(payload, dict):
        return spec_from_mapping(payload)
    return None
