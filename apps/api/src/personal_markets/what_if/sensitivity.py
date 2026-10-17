from __future__ import annotations

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import price_family
from personal_markets.forecasting.hiring import STAGE_CHAIN, build_hiring_numeric_inputs
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.assumptions import editable_assumption_names
from personal_markets.what_if.baseline_state import proposal_from_goal, resolve_simulation_context
from personal_markets.what_if.domain import (
    Assumption,
    SensitivityResult,
    SimulationConfig,
    WhatIfRequest,
)
from personal_markets.what_if.simulation import SimulationEngine


def compute_sensitivity(
    *,
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    request: WhatIfRequest,
    assumptions: list[Assumption],
    baseline_probability: float,
    intervention_effect: float,
    mode: str,
    engine: SimulationEngine,
) -> list[SensitivityResult]:
    if mode == "deadline_event":
        return _hazard_sensitivity(
            goal=goal,
            evidence=evidence,
            assumptions=assumptions,
            baseline_probability=baseline_probability,
        )
    return _continuous_sensitivity(
        request=request,
        assumptions=assumptions,
        baseline_probability=baseline_probability,
        intervention_effect=intervention_effect,
        engine=engine,
    )


def _continuous_sensitivity(
    *,
    request: WhatIfRequest,
    assumptions: list[Assumption],
    baseline_probability: float,
    intervention_effect: float,
    engine: SimulationEngine,
) -> list[SensitivityResult]:
    indexed = {item.name: item for item in assumptions}
    values = {item.name: item.value for item in assumptions}
    required = {
        "flow",
        "growth_mean",
        "growth_volatility",
        "shock_probability",
        "shock_fraction",
        "execution_probability",
    }
    if not required.issubset(values):
        return []

    config = request.config.model_copy(
        update={"minimum_draws": 2000, "batch_draws": 2000, "maximum_draws": 2000}
    )
    results: list[SensitivityResult] = []
    for name in editable_assumption_names(assumptions):
        if name not in indexed or name not in required:
            continue
        assumption = indexed[name]
        lower = max(assumption.minimum, assumption.value - assumption.step)
        upper = min(assumption.maximum, assumption.value + assumption.step)
        lower_prob = _continuous_probability(
            request=request,
            values={**values, name: lower},
            intervention_effect=intervention_effect,
            config=config,
            engine=engine,
        )
        upper_prob = _continuous_probability(
            request=request,
            values={**values, name: upper},
            intervention_effect=intervention_effect,
            config=config,
            engine=engine,
        )
        results.append(
            _result_row(
                assumption=assumption,
                baseline_probability=baseline_probability,
                lower=lower,
                upper=upper,
                lower_prob=lower_prob,
                upper_prob=upper_prob,
            )
        )
    return sorted(results, key=lambda item: item.swing, reverse=True)


def _continuous_probability(
    *,
    request: WhatIfRequest,
    values: dict[str, float],
    intervention_effect: float,
    config: SimulationConfig,
    engine: SimulationEngine,
) -> float:
    paired = engine.continuous_target(
        current_value=request.current_value,
        target_value=request.target_value,
        periods=request.periods,
        direction=request.direction,
        flow=values["flow"],
        growth_mean=values["growth_mean"],
        growth_volatility=values["growth_volatility"],
        shock_probability=values["shock_probability"],
        shock_fraction=values["shock_fraction"],
        execution_probability=values["execution_probability"],
        intervention_effect=intervention_effect,
        config=config,
    )
    return float(np.mean(paired.scenario_success))


def _hazard_sensitivity(
    *,
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    assumptions: list[Assumption],
    baseline_probability: float,
) -> list[SensitivityResult]:
    registry = ForecastModelRegistry()
    model = registry.select(goal)
    proposal = proposal_from_goal(goal)
    indexed = {item.name: item for item in assumptions}
    baseline_values = {item.name: item.value for item in assumptions}
    results: list[SensitivityResult] = []

    for name in editable_assumption_names(assumptions):
        assumption = indexed.get(name)
        if assumption is None:
            continue
        lower = max(assumption.minimum, assumption.value - assumption.step)
        upper = min(assumption.maximum, assumption.value + assumption.step)
        lower_prob = _hazard_probability(
            goal, proposal, evidence, baseline_values, name, lower, model
        )
        upper_prob = _hazard_probability(
            goal, proposal, evidence, baseline_values, name, upper, model
        )
        if lower_prob is None or upper_prob is None:
            continue
        results.append(
            _result_row(
                assumption=assumption,
                baseline_probability=baseline_probability,
                lower=lower,
                upper=upper,
                lower_prob=lower_prob,
                upper_prob=upper_prob,
            )
        )
    return sorted(results, key=lambda item: item.swing, reverse=True)


def _hazard_probability(
    goal: GoalContract,
    proposal: object,
    evidence: list[NormalizedEvidence],
    baseline_values: dict[str, float],
    assumption_name: str,
    value: float,
    model: object,
) -> float | None:
    overrides: dict[str, float] = {}
    if assumption_name == "weekly_application_rate":
        overrides["weekly_application_rate"] = value
    elif assumption_name in STAGE_CHAIN:
        overrides[assumption_name] = value
    elif assumption_name == "execution_probability":
        ctx = resolve_simulation_context(
            goal,
            evidence,
            assumption_overrides={**baseline_values, assumption_name: value},
        )
        return ctx.baseline_probability
    else:
        return None

    merged = dict(baseline_values)
    merged[assumption_name] = value
    numeric = build_hiring_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    if numeric is None:
        return None
    priced = price_family(model, goal, numeric)
    return priced.raw_probability


def _result_row(
    *,
    assumption: Assumption,
    baseline_probability: float,
    lower: float,
    upper: float,
    lower_prob: float,
    upper_prob: float,
) -> SensitivityResult:
    swing = abs(upper_prob - lower_prob) * 100
    if upper_prob > lower_prob:
        direction = "increases"
    elif upper_prob < lower_prob:
        direction = "decreases"
    else:
        direction = "mixed"
    label = assumption.description.split(".")[0] if assumption.description else assumption.name.replace("_", " ")
    return SensitivityResult(
        assumption_id=assumption.id or assumption.name,
        label=label,
        baseline_value=assumption.value,
        lower_value=lower,
        upper_value=upper,
        probability_at_lower=lower_prob,
        probability_at_baseline=baseline_probability,
        probability_at_upper=upper_prob,
        swing=swing,
        direction=direction,
    )


def outcome_distribution_bins(outcomes: np.ndarray, *, bins: int = 12) -> list[dict[str, float]]:
    if outcomes.size == 0:
        return []
    lower_edge = float(np.min(outcomes))
    upper_edge = float(np.max(outcomes))
    if lower_edge == upper_edge:
        return [{"lower": lower_edge, "upper": upper_edge, "mass": 1.0}]
    counts, edges = np.histogram(outcomes, bins=bins, range=(lower_edge, upper_edge))
    total = float(outcomes.size)
    return [
        {
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "mass": float(counts[index] / total),
        }
        for index in range(len(counts))
        if counts[index] > 0
    ]
