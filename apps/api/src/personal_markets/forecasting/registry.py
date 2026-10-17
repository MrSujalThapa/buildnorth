from dataclasses import dataclass
from typing import TYPE_CHECKING

from personal_markets.forecasting.families import (
    ContinuousTargetModel,
    DeadlineEventModel,
    ForecastModelFamily,
    HabitPersistenceModel,
    MultiOutcomeScenarioModel,
    ThresholdModel,
)
from personal_markets.goals.domain import GoalContract

if TYPE_CHECKING:
    from personal_markets.forecasting.engine import NumericInputs


@dataclass(frozen=True, slots=True)
class ApplicabilityDecision:
    applicable: bool
    status: str
    reasons: tuple[str, ...]


class OuladCompletionApplicabilityPolicy:
    supported_goal_type = "deadline_event"
    supported_metric = "course_completion"

    def evaluate(self, goal_type: str, metric: str, checkpoint_day: int) -> ApplicabilityDecision:
        reasons: list[str] = []
        if goal_type != self.supported_goal_type:
            reasons.append(f"unsupported goal type: {goal_type}")
        if metric != self.supported_metric:
            reasons.append(f"unsupported metric: {metric}")
        if checkpoint_day not in (14, 35, 70, 105):
            reasons.append(f"unsupported checkpoint day: {checkpoint_day}")
        return ApplicabilityDecision(
            not reasons, "CALIBRATED" if not reasons else "EXPLORATORY", tuple(reasons)
        )


class ForecastModelRegistry:
    def __init__(self, models: tuple[ForecastModelFamily, ...] | None = None) -> None:
        self._models = models or (
            DeadlineEventModel(),
            ContinuousTargetModel(),
            ThresholdModel(),
            HabitPersistenceModel(),
            MultiOutcomeScenarioModel(),
        )

    def select(self, goal: GoalContract) -> ForecastModelFamily:
        matches = [model for model in self._models if model.supports(goal)]
        if len(matches) != 1:
            raise ValueError(
                f"expected one model family for {goal.goal_type}, found {len(matches)}"
            )
        return matches[0]

    def select_for(
        self, goal: GoalContract, inputs: "NumericInputs | None" = None
    ) -> ForecastModelFamily:
        """Pick the family whose math matches the inputs that were actually built.

        Goal type alone is ambiguous: a savings target and a race time are both
        THRESHOLD goals, but one advances a balance by a monetary flow and the other
        extrapolates a pace trend. Selecting on goal type alone priced savings goals
        with the running model. The assumptions a domain builder emits identify the
        contract it filled, so they decide the family.
        """
        if inputs is not None:
            if "return_distribution" in inputs.assumptions:
                return self.family_named("continuous_target_transition", goal)
            if "trend" in inputs.assumptions or "measurement_noise" in inputs.assumptions:
                return self.family_named("threshold_trend", goal)
        return self.select(goal)

    def family_named(self, family: str, goal: GoalContract) -> ForecastModelFamily:
        for model in self._models:
            if model.descriptor.family == family:
                return model
        return self.select(goal)

    def descriptors(self) -> tuple[object, ...]:
        return tuple(model.descriptor for model in self._models)
