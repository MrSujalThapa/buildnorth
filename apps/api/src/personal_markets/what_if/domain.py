from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from personal_markets.forecasting.families import AssumptionSource


class Assumption(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    value: float
    minimum: float
    maximum: float
    step: float = Field(gt=0)
    source: AssumptionSource
    unit: str
    provenance: str = ""
    editable: bool = True
    scope: str = "simulation"
    model_family: str = ""
    version: str = "1.0.0"
    timestamp: str = ""

    @model_validator(mode="before")
    @classmethod
    def default_id(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("id") and data.get("name"):
            data = {**data, "id": data["name"]}
        return data

    @model_validator(mode="after")
    def value_in_range(self) -> Assumption:
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("assumption value must be within its range")
        if not self.id:
            object.__setattr__(self, "id", self.name)
        return self


class ResourceCost(BaseModel):
    hours_per_week: float = Field(default=0, ge=0)
    money: float = Field(default=0, ge=0)
    energy: float = Field(default=0, ge=0)


class ResourceBudget(BaseModel):
    hours_per_week: float = Field(default=0, ge=0)
    money_per_month: float = Field(default=0, ge=0)


class ResourceUsage(BaseModel):
    hours_per_week: float = Field(default=0, ge=0)
    money_per_month: float = Field(default=0, ge=0)
    within_budget: bool = True
    over_budget_notes: list[str] = Field(default_factory=list)


class StructuredIntervention(BaseModel):
    id: str
    title: str
    action_type: str
    target_dimension: str
    amount: float
    unit: str
    duration_periods: int = Field(gt=0)
    effect_per_unit: float | None = None
    effect_source: AssumptionSource | None = None
    diminishing_return: float = Field(default=0, ge=0)
    cost: ResourceCost = Field(default_factory=ResourceCost)
    exclusivity_group: str | None = None
    execution_probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def effect_has_source(self) -> StructuredIntervention:
        if (self.effect_per_unit is None) != (self.effect_source is None):
            raise ValueError("numeric effects require an explicit source")
        return self


class SimulationConfig(BaseModel):
    seed: int = 20260829
    minimum_draws: int = Field(default=2000, ge=100)
    batch_draws: int = Field(default=2000, ge=100)
    maximum_draws: int = Field(default=20000, ge=100)
    probability_se_tolerance: float = Field(default=0.0075, gt=0)

    @model_validator(mode="after")
    def valid_draw_bounds(self) -> SimulationConfig:
        if self.minimum_draws > self.maximum_draws:
            raise ValueError("minimum_draws cannot exceed maximum_draws")
        return self


class InterventionChangeInput(BaseModel):
    metric: str
    operation: str
    value: float
    unit: str
    frequency: str | None = None
    scope: str = "goal_state"
    provenance: str


class WhatIfRequest(BaseModel):
    goal_id: str
    current_value: float
    target_value: float
    periods: int = Field(gt=0)
    direction: Literal["at_least", "at_most"] = "at_least"
    assumptions: list[Assumption]
    intervention: StructuredIntervention | None = None
    parsed_changes: list[InterventionChangeInput] = Field(default_factory=list)
    config: SimulationConfig = Field(default_factory=SimulationConfig)


class SimulationDiagnostics(BaseModel):
    n_draws: int
    seed: int
    converged: bool
    criterion: str
    achieved_mc_error: float
    duration_ms: float


class DistributionBin(BaseModel):
    lower: float
    upper: float
    mass: float = Field(ge=0, le=1)


class SensitivityResult(BaseModel):
    assumption_id: str
    label: str
    baseline_value: float
    lower_value: float
    upper_value: float
    probability_at_lower: float
    probability_at_baseline: float
    probability_at_upper: float
    swing: float
    direction: Literal["increases", "decreases", "mixed"] = "mixed"
    assumption: str = ""
    probability_swing_pp: float = 0.0
    lower_probability: float = 0.0
    upper_probability: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def legacy_aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "assumption_id" not in payload and payload.get("assumption"):
            payload["assumption_id"] = payload["assumption"]
        if "label" not in payload and payload.get("assumption"):
            payload["label"] = str(payload["assumption"]).replace("_", " ")
        if "swing" not in payload and "probability_swing_pp" in payload:
            payload["swing"] = payload["probability_swing_pp"]
        if "probability_at_lower" not in payload and "lower_probability" in payload:
            payload["probability_at_lower"] = payload["lower_probability"]
        if "probability_at_upper" not in payload and "upper_probability" in payload:
            payload["probability_at_upper"] = payload["upper_probability"]
        return payload

    @model_validator(mode="after")
    def sync_legacy_fields(self) -> SensitivityResult:
        object.__setattr__(self, "assumption", self.assumption or self.assumption_id)
        object.__setattr__(self, "probability_swing_pp", self.swing)
        object.__setattr__(self, "lower_probability", self.probability_at_lower)
        object.__setattr__(self, "upper_probability", self.probability_at_upper)
        return self


class WhatIfResult(BaseModel):
    contract_version: int = 1
    priced: bool
    status: str
    message: str | None = None
    baseline_probability: float | None = None
    scenario_probability: float | None = None
    conditional_on_execution_probability: float | None = None
    execution_probability: float | None = None
    expected_uplift_pp: float | None = None
    uplift_interval_pp: tuple[float, float] | None = None
    p_uplift_positive: float | None = None
    outcome_quantiles: dict[str, float] = Field(default_factory=dict)
    expected_outcome: float | None = None
    downside_probability: float | None = None
    fan: list[dict[str, float]] = Field(default_factory=list)
    distribution_bins: list[DistributionBin] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    opportunity_costs: list[str] = Field(default_factory=list)
    resource_usage: ResourceUsage | None = None
    resource_budget: ResourceBudget | None = None
    resource_feasible: bool = True
    diagnostics: SimulationDiagnostics | None = None
    sensitivity: list[SensitivityResult] = Field(default_factory=list)
    fragility_pp: float | None = None
    run_id: str | None = None
    persisted: bool = False
    history_snapshot_created: bool = False
    receipt: dict[str, object] = Field(default_factory=dict)
    llm_calls: int = 0
    total_latency_ms: float | None = None
    execution_breakdown: dict[str, object] | None = None
    behavior_profile: dict[str, object] | None = None


class MissingStateInput(BaseModel):
    """A state variable the model needs that the goal does not yet have."""

    key: str
    label: str
    unit: str
    why: str
    example: str | None = None
    suggested_sources: list[str] = Field(default_factory=list)


class SatisfiedStateInput(BaseModel):
    key: str
    label: str
    value: float
    source: str
    detail: str


class PriceabilityView(BaseModel):
    """Why the goal is or is not priced, in terms the user can act on."""

    status: Literal["PRICED", "ASSUMPTION_REQUIRED", "NOT_PRICED"]
    headline: str
    model_family: str
    reason: str | None = None
    missing: list[MissingStateInput] = Field(default_factory=list)
    satisfied: list[SatisfiedStateInput] = Field(default_factory=list)


class WhatIfBaselineState(BaseModel):
    goal_id: str
    priced: bool
    status: str
    message: str | None = None
    priceability: PriceabilityView | None = None
    current_value: float | None = None
    target_value: float | None = None
    periods: int | None = None
    direction: Literal["at_least", "at_most"] = "at_least"
    current_probability: float | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    default_intervention: StructuredIntervention | None = None
    model_family: str
    model_version: str
    evidence_count: int = 0
    evidence_watermark: str = "none"
    reference_versions: list[str] = Field(default_factory=list)
    domain_state: dict[str, object] = Field(default_factory=dict)
    resource_constraints: ResourceCost = Field(default_factory=ResourceCost)
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    limitations: list[str] = Field(default_factory=list)
    config: SimulationConfig = Field(default_factory=SimulationConfig)
    compare_candidates: list[CompareCandidate] = Field(default_factory=list)


class CompareCandidate(BaseModel):
    id: str
    title: str
    intervention: StructuredIntervention
    provenance: list[str] = Field(default_factory=list)


class MarketHistoryPointResponse(BaseModel):
    id: str
    probability: float = Field(ge=0, le=1)
    forecast_status: str
    evidence_watermark: str
    model_family: str
    model_version: str
    assumption_hash: str
    simulation_run_id: str | None = None
    source_kind: str = "published_forecast"
    created_at: str | None = None


class WhatIfExplorationResponse(BaseModel):
    """A persisted What If scenario run, surfaced for Past What Ifs."""

    id: str
    goal_id: str
    run_kind: str
    status: str
    created_at: str | None = None
    intervention_title: str | None = None
    baseline_probability: float | None = None
    scenario_probability: float | None = None
    conditional_on_execution_probability: float | None = None
    execution_probability: float | None = None
    expected_uplift_pp: float | None = None


class ResourceLimitsInput(BaseModel):
    hours_per_week: float = Field(ge=0)
    money: float = Field(ge=0)
    energy: float = Field(ge=0)


class ContinuousSearchVariable(BaseModel):
    assumption: str
    increasing: bool = True


class TargetSearchRequest(BaseModel):
    base: WhatIfRequest
    target_probability: float = Field(ge=0, le=1)
    candidates: list[StructuredIntervention] = Field(default_factory=list)
    limits: ResourceLimitsInput
    continuous_variable: ContinuousSearchVariable | None = None
    probability_tolerance: float = Field(default=0.01, gt=0, le=0.1)


class TargetPath(BaseModel):
    label: str
    action_ids: list[str]
    resulting_probability: float = Field(ge=0, le=1)
    resource_cost: ResourceCost
    assumptions: list[Assumption]
    fragility_pp: float | None
    valid_because: str
    model_provenance: dict[str, str]


class TargetSearchResult(BaseModel):
    contract_version: int = 1
    target_probability: float
    current_probability: float
    gap_pp: float
    feasible: bool
    message: str
    paths: list[TargetPath] = Field(default_factory=list)
    search_method: str
    run_id: str | None = None
    receipt: dict[str, object] = Field(default_factory=dict)


class FrontierPoint(BaseModel):
    id: str
    label: str
    resource_cost: float
    expected_uplift_pp: float
    dominated: bool
    action_ids: list[str]
    opportunity_costs: list[str]
    assumptions: list[str]
    provenance: list[str]


class ActionFrontierResult(BaseModel):
    points: list[FrontierPoint]
    frontier_ids: list[str]
    selected_id: str | None


class ScenarioOutcome(BaseModel):
    label: str
    probability: float | None = Field(default=None, ge=0, le=1)
    parameter_source: AssumptionSource | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    downside: bool = False


class ScenarioDistribution(BaseModel):
    outcomes: list[ScenarioOutcome]
    mutually_exclusive: bool = True
    collectively_exhaustive: bool = True
    other_probability: float = Field(default=0, ge=0, le=1)
    assumptions: list[Assumption] = Field(default_factory=list)
    evidence_basis: list[str] = Field(default_factory=list)
    seed: int
    model_version: str
    priced: bool = True
    message: str | None = None
    run_id: str | None = None
    receipt: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def probabilities_sum(self) -> ScenarioDistribution:
        probabilities = [item.probability for item in self.outcomes]
        if self.priced and any(item is None for item in probabilities):
            raise ValueError("priced scenarios require every outcome probability")
        total = sum(item or 0 for item in probabilities) + self.other_probability
        if self.priced and abs(total - 1) > 1e-6:
            raise ValueError("scenario probabilities must sum to one")
        return self


class ScenarioDefinition(BaseModel):
    label: str
    weight: float | None = Field(default=None, ge=0)
    weight_source: AssumptionSource | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    downside: bool = False

    @model_validator(mode="after")
    def numeric_weight_has_source(self) -> ScenarioDefinition:
        if (self.weight is None) != (self.weight_source is None):
            raise ValueError("numeric scenario weights require explicit provenance")
        return self


class PossibleFuturesRequest(BaseModel):
    goal_id: str
    name: str
    outcomes: list[ScenarioDefinition] = Field(min_length=1)
    mutually_exclusive: bool = True
    collectively_exhaustive: bool = True
    include_other: bool = True
    assumptions: list[Assumption] = Field(default_factory=list)
    evidence_basis: list[str] = Field(default_factory=list)
    seed: int = 20260829


class PathDefinition(BaseModel):
    id: str
    label: str
    intervention: StructuredIntervention
    secondary_outcomes: dict[str, float] = Field(default_factory=dict)


class PathComparisonRequest(BaseModel):
    base: WhatIfRequest
    paths: list[PathDefinition] = Field(min_length=2)


class PathComparisonItem(BaseModel):
    id: str
    label: str
    primary_goal_probability: float
    expected_outcome: float
    median: float
    p10: float
    p90: float
    downside_probability: float
    fragility_pp: float | None
    resource_cost: ResourceCost
    execution_probability: float
    assumptions: list[Assumption]
    model_status: str
    secondary_outcomes: dict[str, float]


class PathComparisonResult(BaseModel):
    contract_version: int = 1
    paths: list[PathComparisonItem]
    model_family: str
    model_version: str
    seed: int
    run_id: str | None = None
    receipt: dict[str, object] = Field(default_factory=dict)
