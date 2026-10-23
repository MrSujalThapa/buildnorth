"""Deterministic course-grade arithmetic.

This never publishes a forecast probability and never writes evidence. Unknown
exam results stay unknown unless the caller supplies an explicit hypothetical
score. Multiple unknown components make a required remaining mark
underdetermined unless the caller treats them as one shared remaining score.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from personal_markets.core.errors import SemanticProviderError

MAX_SCORE = 100.0
ScenarioScore = Annotated[float, Field(ge=0, le=MAX_SCORE, allow_inf_nan=False)]
WEIGHT_FRACTION_TOTAL = (0.99, 1.01)
WEIGHT_PERCENT_TOTAL = (99.0, 101.0)


class GradeComponent(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    score: float | None = Field(default=None, ge=0, le=MAX_SCORE, allow_inf_nan=False)
    weight: float = Field(gt=0, le=MAX_SCORE, allow_inf_nan=False)
    known: bool = True


class CourseGradeScenario(BaseModel):
    label: str
    remaining_score: float
    average: float
    meets_target: bool | None = None


class CourseGradeRequest(BaseModel):
    components: list[GradeComponent] = Field(min_length=1, max_length=20)
    target: float | None = Field(default=None, ge=0, le=MAX_SCORE, allow_inf_nan=False)
    remaining_score: float | None = Field(default=None, ge=0, le=MAX_SCORE, allow_inf_nan=False)
    scenarios: list[ScenarioScore] = Field(default_factory=list, max_length=8)


class CourseGradeResult(BaseModel):
    status: str
    average: float | None = None
    known_contribution: float | None = None
    known_weight: float | None = None
    remaining_weight: float | None = None
    required_remaining: float | None = None
    required_is_uniform: bool = False
    unattainable: bool = False
    already_met: bool = False
    scenarios: list[CourseGradeScenario] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    message: str
    arithmetic_only: bool = True
    writes_evidence: bool = False


def weights_as_fractions(components: list[GradeComponent]) -> list[float]:
    total = sum(item.weight for item in components)
    if WEIGHT_FRACTION_TOTAL[0] <= total <= WEIGHT_FRACTION_TOTAL[1]:
        return [item.weight / total for item in components]
    if WEIGHT_PERCENT_TOTAL[0] <= total <= WEIGHT_PERCENT_TOTAL[1]:
        return [item.weight / total for item in components]
    raise SemanticProviderError(
        "Component weights must sum to 1 (fractions) or 100 (percent). "
        f"Received {total:g}."
    )


def _is_known(item: GradeComponent) -> bool:
    return item.known and item.score is not None


def evaluate_course_grade(request: CourseGradeRequest) -> CourseGradeResult:
    fractions = weights_as_fractions(request.components)
    known_contribution = 0.0
    known_weight = 0.0
    remaining_weight = 0.0
    unknown: list[str] = []
    questions: list[str] = []
    for item, fraction in zip(request.components, fractions, strict=True):
        if _is_known(item):
            known_contribution += float(item.score) * fraction
            known_weight += fraction
            continue
        remaining_weight += fraction
        unknown.append(item.label)
        questions.append(
            f"What score (0-100) should we use for {item.label} "
            f"({fraction * 100:g}% of the total)?"
        )

    required, required_uniform, unattainable, already_met = _required_remaining(
        known_contribution, remaining_weight, request.target, unknown
    )

    if remaining_weight > 1e-9 and request.remaining_score is None and not request.scenarios:
        missing = list(unknown)
        if len(unknown) > 1 and request.target is not None:
            missing.append(
                "a single remaining component, or one shared remaining score, "
                "before a required remaining mark can be solved"
            )
        return CourseGradeResult(
            status="needs_scores",
            known_contribution=known_contribution,
            known_weight=known_weight,
            remaining_weight=remaining_weight,
            required_remaining=required,
            required_is_uniform=required_uniform,
            unattainable=unattainable,
            already_met=already_met,
            questions=questions
            or ["What score should be used for the remaining weighted component(s)?"],
            missing=missing,
            message=(
                "The course average cannot be completed until every remaining "
                "component has a score. This is arithmetic, not a forecast, and "
                "hypothetical scores are not stored as evidence."
            ),
        )

    average = known_contribution
    if remaining_weight > 1e-9 and request.remaining_score is not None:
        average += request.remaining_score * remaining_weight
    elif remaining_weight > 1e-9:
        average = None

    scenarios = [
        _scenario(score, known_contribution, remaining_weight, request.target)
        for score in request.scenarios
        if remaining_weight > 1e-9
    ]
    if request.remaining_score is not None and remaining_weight > 1e-9:
        labeled = _scenario(
            request.remaining_score, known_contribution, remaining_weight, request.target
        )
        if all(item.remaining_score != labeled.remaining_score for item in scenarios):
            scenarios.insert(0, labeled)

    if average is None:
        status = "underdetermined" if len(unknown) > 1 else "needs_scores"
        return CourseGradeResult(
            status=status,
            known_contribution=known_contribution,
            known_weight=known_weight,
            remaining_weight=remaining_weight,
            required_remaining=required,
            required_is_uniform=required_uniform,
            unattainable=unattainable,
            already_met=already_met,
            scenarios=scenarios,
            questions=questions,
            missing=unknown,
            message=(
                "Remaining components differ, so a single completed average is "
                "underdetermined. Named hypotheticals below are not evidence."
                if scenarios
                else "Remaining component scores are still missing."
            ),
        )

    return CourseGradeResult(
        status="computed",
        average=average,
        known_contribution=known_contribution,
        known_weight=known_weight,
        remaining_weight=remaining_weight,
        required_remaining=required,
        required_is_uniform=required_uniform,
        unattainable=unattainable,
        already_met=already_met,
        scenarios=scenarios,
        questions=questions,
        message=_computed_message(
            average, request.target, required, required_uniform, unattainable, already_met
        ),
    )


def _required_remaining(
    known_contribution: float,
    remaining_weight: float,
    target: float | None,
    unknown: list[str],
) -> tuple[float | None, bool, bool, bool]:
    if target is None:
        return None, False, False, False
    if remaining_weight <= 1e-9:
        met = known_contribution + 1e-9 >= target
        return None, False, not met, met
    if len(unknown) > 1:
        required = (target - known_contribution) / remaining_weight
        return required, True, required > MAX_SCORE + 1e-9, required < -1e-9
    required = (target - known_contribution) / remaining_weight
    return required, False, required > MAX_SCORE + 1e-9, required < -1e-9


def _scenario(
    remaining_score: float,
    known_contribution: float,
    remaining_weight: float,
    target: float | None,
) -> CourseGradeScenario:
    average = known_contribution + remaining_score * remaining_weight
    meets = None if target is None else average + 1e-9 >= target
    return CourseGradeScenario(
        label=f"remaining={remaining_score:g}",
        remaining_score=remaining_score,
        average=average,
        meets_target=meets,
    )


def _computed_message(
    average: float,
    target: float | None,
    required: float | None,
    required_uniform: bool,
    unattainable: bool,
    already_met: bool,
) -> str:
    parts = [
        f"Weighted course standing is {average:.2f} out of 100. "
        "This is deterministic arithmetic from the supplied weights and scores, "
        "not a causal effect and not a published forecast."
    ]
    if already_met:
        parts.append("The known components already meet the target.")
    elif unattainable:
        parts.append("The target is unattainable even with 100 on remaining work.")
    elif required is not None and target is not None:
        qualifier = (
            " on remaining work (same score on every still-unknown component)."
            if required_uniform
            else " on the remaining component."
        )
        parts.append(f"Reaching {target:g} requires {required:.2f}{qualifier}")
    parts.append("Hypothetical remaining scores are not written to evidence.")
    return " ".join(part for part in parts if part)
