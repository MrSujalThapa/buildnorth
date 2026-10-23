"""Deterministic weighted-score arithmetic for conversational What If.

This never prices a forecast. It only computes a weighted average when every
weight and known score is supplied. Missing remaining scores stay unpriced.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from personal_markets.core.errors import SemanticProviderError
from personal_markets.forecasting.course_grade import (
    CourseGradeRequest,
    GradeComponent,
    evaluate_course_grade,
)

WeightedComponent = GradeComponent


class WeightedScoreRequest(BaseModel):
    components: list[WeightedComponent] = Field(min_length=1, max_length=20)
    remaining_score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class WeightedScoreResult(BaseModel):
    status: str
    average: float | None = None
    known_weight: float | None = None
    remaining_weight: float | None = None
    questions: list[str] = Field(default_factory=list)
    message: str
    arithmetic_only: bool = True


def compute_weighted_score(request: WeightedScoreRequest) -> WeightedScoreResult:
    try:
        result = evaluate_course_grade(
            CourseGradeRequest(
                components=request.components, remaining_score=request.remaining_score
            )
        )
    except SemanticProviderError as error:
        raise ValueError(str(error)) from error
    status = (
        "needs_clarification"
        if result.status in {"needs_scores", "underdetermined"}
        else result.status
    )
    return WeightedScoreResult(
        status=status,
        average=result.average,
        known_weight=result.known_weight,
        remaining_weight=result.remaining_weight,
        questions=result.questions,
        message=result.message,
        arithmetic_only=True,
    )
