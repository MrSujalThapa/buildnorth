from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class EvaluationCase(BaseModel):
    case_id: str
    subject_id: str
    checkpoint_at: datetime
    goal_definition: dict[str, object]
    evidence: list[dict[str, object]]
    outcome: int = Field(ge=0, le=1)


class ForecastResult(BaseModel):
    case_id: str
    probability: float = Field(ge=0, le=1)
    system: str
    model_version: str


class BenchmarkDataset(Protocol):
    @property
    def version(self) -> str: ...

    def load_cases(self) -> list[EvaluationCase]: ...


class EvaluationSystem(Protocol):
    async def predict(self, case: EvaluationCase) -> ForecastResult: ...
