from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import ceil
from typing import Any

import numpy as np

from personal_markets.forecasting.families import (
    DeadlineEventModel,
    ForecastModelFamily,
    HabitPersistenceModel,
    receipt_model_metadata,
)
from personal_markets.goals.domain import GoalContract


@dataclass(frozen=True, slots=True)
class NumericInputs:
    """Explicit numerical state and assumptions. Missing keys stay unpriced."""

    state: dict[str, Any] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    assumption_sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FamilyPrice:
    priced: bool
    raw_probability: float | None
    forecast_status: str
    limitations: list[str]
    transforms: dict[str, Any]
    used_assumptions: list[dict[str, Any]]


def price_family(
    model: ForecastModelFamily, goal: GoalContract, inputs: NumericInputs
) -> FamilyPrice:
    """Price through the registry-selected family. Never invent a default probability."""
    family = model.descriptor.family
    if family == "deadline_event_hazard":
        return _deadline_event(model, goal, inputs)
    if family == "continuous_target_transition":
        return _continuous_target(model, goal, inputs)
    if family == "threshold_trend":
        return _threshold_trend(model, goal, inputs)
    if family == "habit_beta_recency":
        return _habit(model, inputs)
    if family == "multi_outcome_transition":
        return _multi_outcome(model, goal, inputs)
    missing = _missing(model, inputs)
    return _unpriced(
        model,
        [
            f"{family} cannot price this baseline without typed numerical inputs: "
            + ", ".join(missing or model.descriptor.required_state)
        ],
    )


def _deadline_event(
    model: ForecastModelFamily, goal: GoalContract, inputs: NumericInputs
) -> FamilyPrice:
    transforms: dict[str, Any] = {}
    logits = _logits(inputs)
    periods = inputs.state.get("periods_remaining")
    if periods is None and logits is not None and logits.size == 0:
        logits = None
    if periods is None and (logits is None or logits.size == 1):
        periods = max(1, ceil((goal.deadline - datetime.now(UTC)).total_seconds() / 604800))
        transforms["periods_remaining"] = {
            "value": periods,
            "source": "REAL_USER_EVIDENCE",
            "transform": "weeks_until_goal_deadline",
        }
    period_count = int(periods) if periods is not None else 1
    if logits is None:
        return _unpriced(
            model,
            [
                "deadline_event_hazard requires baseline_logit or baseline_logits from "
                "REFERENCE_DATA, FITTED evidence, or an explicit USER_ASSUMPTION."
            ],
            transforms,
        )
    if logits.size == 1:
        logits = np.full(period_count, float(logits[0]), dtype=float)
        transforms["logit_broadcast"] = {
            "periods": period_count,
            "source": inputs.assumption_sources.get("baseline_logit", "USER_ASSUMPTION"),
        }
    probability = DeadlineEventModel.probability(logits)
    source = inputs.assumption_sources.get("baseline_logit") or inputs.assumption_sources.get(
        "baseline_logits", "USER_ASSUMPTION"
    )
    extra = inputs.state.get("pricing_transforms")
    if isinstance(extra, dict):
        transforms = {**transforms, **extra}
    status = "ANCHORED" if source == "REFERENCE" else "EXPLORATORY"
    status = _cap_status(status, model)
    return FamilyPrice(
        priced=True,
        raw_probability=probability,
        forecast_status=status,
        limitations=list(model.descriptor.extrapolation_limits),
        transforms=transforms,
        used_assumptions=[
            {
                "id": "baseline_logit",
                "name": "baseline_logit",
                "value": logits.tolist(),
                "source": source,
                "unit": "logit",
            }
        ],
    )


def _continuous_target(
    model: ForecastModelFamily, goal: GoalContract, inputs: NumericInputs
) -> FamilyPrice:
    from personal_markets.forecasting.finance import (
        load_finance_reference,
        price_from_numeric_inputs,
    )

    probability, transforms = price_from_numeric_inputs(inputs)
    if probability is None:
        missing = _missing(model, inputs)
        return _unpriced(
            model,
            [
                "continuous_target_transition requires current_value, target_value, periods, "
                "and return_distribution from REAL_USER_EVIDENCE or explicit assumptions.",
                *([f"missing: {', '.join(missing)}"] if missing else []),
            ],
        )
    extra = inputs.state.get("pricing_transforms")
    if isinstance(extra, dict):
        transforms = {**extra, **transforms}
    sources = inputs.assumption_sources
    status = "EXPLORATORY"
    if all(sources.get(key) == "REFERENCE" for key in sources):
        status = "ANCHORED"
    elif any(sources.get(key) == "REFERENCE" for key in sources):
        status = "EXPLORATORY"
    return FamilyPrice(
        priced=True,
        raw_probability=probability,
        forecast_status=_cap_status(status, model),
        limitations=[
            *model.descriptor.extrapolation_limits,
            *load_finance_reference().limitations,
        ],
        transforms=transforms,
        used_assumptions=[
            {
                "id": "return_distribution",
                "name": "return_distribution",
                "value": inputs.assumptions.get("return_distribution"),
                "source": sources.get("annual_return_mean", "REFERENCE"),
            }
        ],
    )


def _threshold_trend(
    model: ForecastModelFamily, goal: GoalContract, inputs: NumericInputs
) -> FamilyPrice:
    from personal_markets.forecasting.running import (
        load_running_reference,
        price_from_numeric_inputs,
    )

    probability, transforms = price_from_numeric_inputs(inputs)
    if probability is None:
        missing = _missing(model, inputs)
        return _unpriced(
            model,
            [
                "threshold_trend requires current_value, target_value, periods, and "
                "trend/measurement_noise from REAL_USER_EVIDENCE or explicit assumptions.",
                *([f"missing: {', '.join(missing)}"] if missing else []),
            ],
        )
    extra = inputs.state.get("pricing_transforms")
    if isinstance(extra, dict):
        transforms = {**extra, **transforms}
    sources = inputs.assumption_sources
    status = "EXPLORATORY"
    has_evidence_trend = (
        sources.get("measurement_noise") == "REAL_USER_EVIDENCE"
        and sources.get("trend") == "REAL_USER_EVIDENCE"
    )
    if has_evidence_trend:
        status = "ANCHORED"
    return FamilyPrice(
        priced=True,
        raw_probability=probability,
        forecast_status=_cap_status(status, model),
        limitations=[
            *model.descriptor.extrapolation_limits,
            *load_running_reference().limitations,
        ],
        transforms=transforms,
        used_assumptions=[
            {
                "id": "trend",
                "name": "trend",
                "value": inputs.assumptions.get("trend"),
                "source": sources.get("trend", "REFERENCE"),
                "unit": "seconds_per_week",
            },
            {
                "id": "measurement_noise",
                "name": "measurement_noise",
                "value": inputs.assumptions.get("measurement_noise"),
                "source": sources.get("measurement_noise", "REFERENCE"),
                "unit": "seconds",
            },
        ],
    )


def _habit(model: ForecastModelFamily, inputs: NumericInputs) -> FamilyPrice:
    history = inputs.state.get("history")
    if not isinstance(history, list) or not history:
        return _unpriced(
            model,
            ["habit_beta_recency requires a non-empty binary history in typed state."],
        )
    if any(item not in (0, 1, True, False) for item in history):
        return _unpriced(model, ["habit history must contain only binary observations."])
    try:
        half_life = float(inputs.assumptions.get("recency_half_life", 28))
        alpha = float(inputs.assumptions["prior_alpha"])
        beta = float(inputs.assumptions["prior_beta"])
    except (KeyError, TypeError, ValueError):
        return _unpriced(
            model,
            ["habit_beta_recency requires explicit prior_alpha and prior_beta assumptions."],
        )
    mean, strength = HabitPersistenceModel.posterior(
        [bool(item) for item in history], half_life, alpha, beta
    )
    return FamilyPrice(
        priced=True,
        raw_probability=mean,
        forecast_status=_cap_status("EXPLORATORY", model),
        limitations=list(model.descriptor.extrapolation_limits),
        transforms={"posterior_strength": strength, "recency_half_life": half_life},
        used_assumptions=[
            {
                "id": "prior_alpha",
                "name": "prior_alpha",
                "value": alpha,
                "source": inputs.assumption_sources.get("prior_alpha", "EXPLORATION_ASSUMPTION"),
            },
            {
                "id": "prior_beta",
                "name": "prior_beta",
                "value": beta,
                "source": inputs.assumption_sources.get("prior_beta", "EXPLORATION_ASSUMPTION"),
            },
        ],
    )


def _multi_outcome(
    model: ForecastModelFamily, goal: GoalContract, inputs: NumericInputs
) -> FamilyPrice:
    weights = inputs.state.get("outcome_weights") or inputs.assumptions.get("outcome_weights")
    if not isinstance(weights, dict) or not weights:
        return _unpriced(
            model,
            [
                "multi_outcome_transition requires mutually exclusive outcome_weights from "
                "reference data or explicit assumptions."
            ],
        )
    try:
        numeric = {str(key): float(value) for key, value in weights.items()}
    except (TypeError, ValueError):
        return _unpriced(model, ["outcome_weights must be numeric."])
    total = sum(numeric.values())
    if abs(total - 1.0) > 1e-6:
        return _unpriced(
            model,
            [f"outcome_weights must sum to 1; received {total:.6f}."],
        )
    target = str(
        goal.success_definition.get("target") or goal.success_definition.get("metric") or ""
    )
    if target not in numeric:
        return _unpriced(
            model,
            [f"No weight was supplied for the goal target outcome {target!r}."],
        )
    source = inputs.assumption_sources.get("outcome_weights", "USER_ASSUMPTION")
    status = "ANCHORED" if source == "REFERENCE" else "EXPLORATORY"
    return FamilyPrice(
        priced=True,
        raw_probability=numeric[target],
        forecast_status=_cap_status(status, model),
        limitations=list(model.descriptor.extrapolation_limits),
        transforms={"outcome_mass": total},
        used_assumptions=[
            {
                "id": "outcome_weights",
                "name": "outcome_weights",
                "value": numeric,
                "source": source,
            }
        ],
    )


def _logits(inputs: NumericInputs) -> np.ndarray | None:
    raw = inputs.state.get("baseline_logits", inputs.assumptions.get("baseline_logits"))
    if raw is None:
        single = inputs.assumptions.get("baseline_logit", inputs.state.get("baseline_logit"))
        if single is None:
            return None
        raw = [single]
    try:
        values = np.asarray(raw, dtype=float)
    except (TypeError, ValueError):
        return None
    if values.size == 0 or not np.all(np.isfinite(values)):
        return None
    return values


def _missing(model: ForecastModelFamily, inputs: NumericInputs) -> list[str]:
    missing: list[str] = []
    for key in model.descriptor.required_state:
        if key not in inputs.state:
            missing.append(key)
    for key in model.descriptor.required_assumptions:
        if key not in inputs.assumptions and key not in inputs.state:
            missing.append(key)
    return missing


def _cap_status(status: str, model: ForecastModelFamily) -> str:
    rank = {"EXPLORATORY": 0, "ANCHORED": 1, "CALIBRATED": 2}
    maximum = model.descriptor.maximum_status.value
    if rank.get(status, 0) > rank.get(maximum, 0):
        return maximum
    return status


def _unpriced(
    model: ForecastModelFamily,
    limitations: list[str],
    transforms: dict[str, Any] | None = None,
) -> FamilyPrice:
    return FamilyPrice(
        priced=False,
        raw_probability=None,
        forecast_status="EXPLORATORY",
        limitations=[
            *limitations,
            "NOT PRICED: no applicable numerical basis was supplied.",
            *model.descriptor.extrapolation_limits,
        ],
        transforms=transforms or {},
        used_assumptions=[],
    )


def family_receipt_metadata(model: ForecastModelFamily) -> dict[str, Any]:
    return receipt_model_metadata(model)
