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


class StrategyPlan(BaseModel):
    family: str
    interpretation: str
    levers: list[StrategyLever]
    needs: list[str] = Field(default_factory=list)
    analysis: list[StrategyAnalysisPoint] = Field(default_factory=list)
    stated_quantity: float | None = None
    modeled: bool = False
