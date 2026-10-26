from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyLever(BaseModel):
    assumption: str
    label: str
    unit: str
    unit_label: str
    baseline_value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    operation: str = "add"
    question: str
    mapping_note: str
    suggested_values: list[float] = Field(default_factory=list)


class StrategyAnalysisPoint(BaseModel):
    heading: str
    body: str


class StrategyInput(BaseModel):
    key: str
    label: str
    unit: str
    minimum: float | None = None
    maximum: float | None = None
    required: bool = True
    value: float | None = None
    suggested_values: list[float] = Field(default_factory=list)


class StrategyOption(BaseModel):
    """One explicit way to turn the strategy into model inputs; the user picks it."""

    id: str
    label: str
    description: str
    proxy: bool = False
    inputs: list[StrategyInput]


class StrategyPlan(BaseModel):
    family: str
    interpretation: str
    levers: list[StrategyLever]
    needs: list[str] = Field(default_factory=list)
    analysis: list[StrategyAnalysisPoint] = Field(default_factory=list)
    stated_quantity: float | None = None
    modeled: bool = False
    affected_outcomes: list[str] = Field(default_factory=list)
    options: list[StrategyOption] = Field(default_factory=list)
    selected_option: str | None = None
    metrics_to_track: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    unpriced: bool = False


class StrategyChangesRequest(BaseModel):
    goal_id: str
    family: str
    text: str = ""
    option_id: str
    inputs: dict[str, float] = Field(default_factory=dict)


class StrategyChangesResponse(BaseModel):
    """Model changes for a chosen option. Empty changes mean a conflict blocked it."""

    option_id: str
    title: str
    changes: list[dict[str, object]] = Field(default_factory=list)
    assumptions_used: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    proxy: bool = False
