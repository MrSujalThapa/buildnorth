from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import numpy as np
from scipy.special import expit

from personal_markets.goals.domain import ForecastStatus, GoalContract, GoalType


class AssumptionSource(StrEnum):
    FITTED = "FITTED"
    REFERENCE = "REFERENCE"
    USER = "USER_ASSUMPTION"
    EXPLORATION = "EXPLORATION_ASSUMPTION"


@dataclass(frozen=True, slots=True)
class ModelFamilyDescriptor:
    family: str
    goal_types: tuple[GoalType, ...]
    required_state: tuple[str, ...]
    optional_state: tuple[str, ...]
    required_assumptions: tuple[str, ...]
    reference_requirements: tuple[str, ...]
    maximum_status: ForecastStatus
    extrapolation_limits: tuple[str, ...]
    supported_interventions: tuple[str, ...]
    simulation_method: str
    version: str = "1.0.0"


class ForecastModelFamily(Protocol):
    descriptor: ModelFamilyDescriptor

    def supports(self, goal: GoalContract) -> bool: ...


class DeadlineEventModel:
    descriptor = ModelFamilyDescriptor(
        family="deadline_event_hazard",
        goal_types=(GoalType.DEADLINE_EVENT,),
        required_state=("periods_remaining",),
        optional_state=("features",),
        required_assumptions=("baseline_logit",),
        reference_requirements=("coefficient_source",),
        maximum_status=ForecastStatus.ANCHORED,
        extrapolation_limits=("coefficients must cover the requested horizon",),
        supported_interventions=("feature_shift", "hazard_multiplier"),
        simulation_method="discrete_time_logistic_hazard",
    )

    def supports(self, goal: GoalContract) -> bool:
        return goal.goal_type is GoalType.DEADLINE_EVENT

    @staticmethod
    def probability(
        baseline_logits: np.ndarray,
        features: np.ndarray | None = None,
        coefficients: np.ndarray | None = None,
    ) -> float:
        logits = np.asarray(baseline_logits, dtype=float)
        if features is not None or coefficients is not None:
            if features is None or coefficients is None:
                raise ValueError("features and coefficients must be supplied together")
            logits = logits + np.asarray(features) @ np.asarray(coefficients)
        hazards = expit(logits)
        return float(1 - np.prod(1 - hazards))


class ContinuousTargetModel:
    descriptor = ModelFamilyDescriptor(
        family="continuous_target_transition",
        goal_types=(GoalType.CONTINUOUS_TARGET,),
        required_state=("current_value", "target_value", "periods"),
        optional_state=("deterministic_flow", "shock_correlation"),
        required_assumptions=("return_distribution",),
        reference_requirements=(),
        maximum_status=ForecastStatus.EXPLORATORY,
        extrapolation_limits=("distribution assumptions are conditional, not calibrated",),
        supported_interventions=("flow_change", "one_time_flow", "return_change"),
        simulation_method="vectorized_state_transition",
    )

    def supports(self, goal: GoalContract) -> bool:
        return goal.goal_type is GoalType.CONTINUOUS_TARGET


class ThresholdModel:
    descriptor = ModelFamilyDescriptor(
        family="threshold_trend",
        goal_types=(GoalType.THRESHOLD,),
        required_state=("current_value", "target_value", "periods"),
        optional_state=("observations", "direction"),
        required_assumptions=("trend", "measurement_noise", "adherence"),
        reference_requirements=(),
        maximum_status=ForecastStatus.EXPLORATORY,
        extrapolation_limits=("sparse evidence remains exploratory",),
        supported_interventions=("trend_change", "adherence_change"),
        simulation_method="trend_with_diminishing_improvement",
    )

    def supports(self, goal: GoalContract) -> bool:
        return goal.goal_type is GoalType.THRESHOLD


class HabitPersistenceModel:
    descriptor = ModelFamilyDescriptor(
        family="habit_beta_recency",
        goal_types=(GoalType.HABIT,),
        required_state=("history",),
        optional_state=("recency_half_life",),
        required_assumptions=("prior_alpha", "prior_beta"),
        reference_requirements=(),
        maximum_status=ForecastStatus.EXPLORATORY,
        extrapolation_limits=("regime changes reduce historical strength",),
        supported_interventions=("adherence_support",),
        simulation_method="recency_weighted_beta_bernoulli",
    )

    def supports(self, goal: GoalContract) -> bool:
        return goal.goal_type is GoalType.HABIT

    @staticmethod
    def posterior(
        history: list[bool], half_life: float = 28, alpha: float = 1, beta: float = 1
    ) -> tuple[float, float]:
        if half_life <= 0 or alpha <= 0 or beta <= 0:
            raise ValueError("half_life and prior parameters must be positive")
        ages = np.arange(len(history) - 1, -1, -1, dtype=float)
        weights = np.exp2(-ages / half_life)
        values = np.asarray(history, dtype=float)
        a = alpha + float(np.sum(weights * values))
        b = beta + float(np.sum(weights * (1 - values)))
        return a / (a + b), a + b


class MultiOutcomeScenarioModel:
    descriptor = ModelFamilyDescriptor(
        family="multi_outcome_transition",
        goal_types=(GoalType.MULTI_OUTCOME,),
        required_state=("outcomes",),
        optional_state=("transition_matrix",),
        required_assumptions=("outcome_weights",),
        reference_requirements=("mutually exclusive outcome basis",),
        maximum_status=ForecastStatus.EXPLORATORY,
        extrapolation_limits=("unpriced when numeric outcome weights are absent",),
        supported_interventions=("transition_shift",),
        simulation_method="categorical_transition",
    )

    def supports(self, goal: GoalContract) -> bool:
        return goal.goal_type is GoalType.MULTI_OUTCOME


def receipt_model_metadata(model: ForecastModelFamily) -> dict[str, Any]:
    descriptor = model.descriptor
    return {
        "family": descriptor.family,
        "version": descriptor.version,
        "simulation_method": descriptor.simulation_method,
        "maximum_status": descriptor.maximum_status.value,
        "extrapolation_limits": list(descriptor.extrapolation_limits),
    }
