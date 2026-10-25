from pydantic import BaseModel, Field

from personal_markets.what_if.strategy_insights import StrategyInsight


class InterventionChangeResponse(BaseModel):
    metric: str
    operation: str
    value: float
    unit: str
    frequency: str | None = None
    scope: str = "goal_state"
    provenance: str


class ParseInterventionRequest(BaseModel):
    goal_id: str
    text: str = Field(min_length=1)


class ParseInterventionResponse(BaseModel):
    raw_text: str
    changes: list[InterventionChangeResponse]
    unsupported: list[str]
    effect_assigned: bool = False
    understood_action: str = ""
    mechanism: list[dict[str, str]] = Field(default_factory=list)
    pricing_status: str = "NOT_PRICED"
    agent_run_id: str | None = None
    limitations: list[str] = Field(default_factory=list)
    research_claims: list[str] = Field(default_factory=list)
    request_kind: str = "quantitative_scenario"
    confirmation_needed: bool = False
    insights: list[StrategyInsight] = Field(default_factory=list)
    consumer_summary: str = ""
    inference_provider: str | None = None
    inference_model: str | None = None


class ParseDecisionRequest(BaseModel):
    goal_id: str
    text: str = Field(min_length=1)


class TypedDecisionResponse(BaseModel):
    action: str
    alternative: str | None = None
    timing: str = "unspecified"
    constraints: list[str] = Field(default_factory=list)


class ParseDecisionResponse(BaseModel):
    raw_text: str
    decision: TypedDecisionResponse | None = None
    scenario_labels: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
