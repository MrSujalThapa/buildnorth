"""Deterministic weighted-score arithmetic for conversational What If.

This never prices a forecast. It only computes a weighted average when every
weight and known score is supplied. Missing remaining scores stay unpriced.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WeightedComponent(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    weight: float = Field(gt=0, le=100, allow_inf_nan=False)
    known: bool = True


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


def _weights_as_fractions(components: list[WeightedComponent]) -> list[float]:
    total = sum(item.weight for item in components)
    if 0.99 <= total <= 1.01:
        return [item.weight / total for item in components]
    if 99 <= total <= 101:
        return [item.weight / total for item in components]
    raise ValueError(
        "Component weights must sum to 1 (fractions) or 100 (percent). "
        f"Received {total:g}."
    )


def compute_weighted_score(request: WeightedScoreRequest) -> WeightedScoreResult:
    fractions = _weights_as_fractions(request.components)
    known = 0.0
    remaining = 0.0
    known_mass = 0.0
    questions: list[str] = []
    for item, fraction in zip(request.components, fractions, strict=True):
        if item.known and item.score is not None:
            known += item.score * fraction
            known_mass += fraction
        else:
            remaining += fraction
            questions.append(
                f"What score (0-100) should we use for {item.label} "
                f"({fraction * 100:g}% of the total)?"
            )
    if remaining > 1e-9 and request.remaining_score is None:
        return WeightedScoreResult(
            status="needs_clarification",
            known_weight=known_mass,
            remaining_weight=remaining,
            questions=questions
            or [
                "What score should be used for the remaining weighted component(s)?"
            ],
            message=(
                "The weighted average cannot be computed until every remaining "
                "component has a score. This is arithmetic, not a forecast."
            ),
        )
    average = known
    if remaining > 1e-9 and request.remaining_score is not None:
        average += request.remaining_score * remaining
    return WeightedScoreResult(
        status="computed",
        average=average,
        known_weight=known_mass,
        remaining_weight=remaining,
        message=(
            f"Weighted average is {average:.2f} out of 100. This is deterministic "
            "arithmetic from the supplied weights and scores, not a causal effect "
            "and not a published forecast."
        ),
    )
