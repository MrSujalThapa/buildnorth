from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.forecasting.finance import is_finance_goal
from personal_markets.forecasting.hiring import (
    STAGE_CHAIN,
    aggregate_funnel_from_evidence,
    build_hiring_numeric_inputs,
    is_hiring_goal,
    load_hiring_reference,
)
from personal_markets.forecasting.running import is_running_goal
from personal_markets.forecasting.startup import futures_outcome_weights, is_startup_goal
from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.baseline_state import proposal_from_goal, resolve_simulation_context
from personal_markets.what_if.domain import (
    InterventionChangeInput,
    ScenarioDefinition,
    SimulationConfig,
)
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import apply_parsed_changes_to_assumptions
from personal_markets.what_if.simulation import SimulationEngine

BandKey = Literal[
    "target_reached",
    "meaningful_progress",
    "current_trajectory",
    "downside",
    "offer",
    "final_stage",
    "technical_stage",
    "screening_stage",
    "no_progress",
]

_BAND_LABEL_TOKENS: dict[BandKey, tuple[str, ...]] = {
    "target_reached": ("target reached", "reaches target", "hit target", "offer", "success"),
    "meaningful_progress": (
        "meaningful progress",
        "near target",
        "modest improvement",
        "technical",
        "final",
        "screening",
    ),
    "current_trajectory": ("current trajectory", "current path", "maintain", "flat"),
    "downside": (
        "downside",
        "regress",
        "far below",
        "fail",
        "stagnat",
        "no progress",
        "shutdown",
    ),
    "offer": ("offer", "target reached", "success"),
    "final_stage": ("final", "late stage"),
    "technical_stage": ("technical", " onsite"),
    "screening_stage": ("screen", "response", "pipeline"),
    "no_progress": ("no progress", "stagnat", "downside"),
}


@dataclass(frozen=True, slots=True)
class ResolvedFuturesWeights:
    outcomes: list[ScenarioDefinition]
    evidence_basis: list[str]
    weight_source: AssumptionSource
    model_version: str


def resolve_futures_weights(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    *,
    scenario_labels: list[str],
    seed: int = 20260829,
    parsed_changes: list[InterventionChangeInput] | None = None,
    config: SimulationConfig | None = None,
) -> ResolvedFuturesWeights | None:
    if is_startup_goal(goal):
        return _startup_weights(goal, evidence, scenario_labels, parsed_changes=parsed_changes)
    if is_finance_goal(goal) or is_running_goal(goal):
        return _continuous_target_mc_weights(
            goal,
            evidence,
            scenario_labels,
            seed=seed,
            parsed_changes=parsed_changes,
            config=config,
        )
    if is_hiring_goal(goal):
        return _career_funnel_weights(
            goal, evidence, scenario_labels, parsed_changes=parsed_changes
        )
    return None


def _startup_overrides_from_changes(
    parsed_changes: list[InterventionChangeInput] | None,
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    for change in parsed_changes or []:
        metric = change.metric
        value = float(change.value)
        if metric in {"fundraising_conversations", "user_conversations_per_week"}:
            if change.operation == "subtract":
                value = -value
            overrides["fundraising_conversations"] = max(0, int(round(value)))
        elif metric in {
            "mrr",
            "revenue",
            "revenue_growth_rate",
            "users",
            "runway_months",
            "burn_monthly",
        }:
            overrides[metric] = value
        elif metric == "term_sheet":
            overrides["term_sheet"] = value >= 1
    return overrides


def _startup_weights(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    scenario_labels: list[str],
    *,
    parsed_changes: list[InterventionChangeInput] | None = None,
) -> ResolvedFuturesWeights | None:
    weights, _message = futures_outcome_weights(
        goal,
        evidence,
        scenario_labels=scenario_labels,
        state_overrides=_startup_overrides_from_changes(parsed_changes),
    )
    if not weights:
        return None
    outcomes = _definitions_from_map(scenario_labels, weights, AssumptionSource.REFERENCE)
    if not outcomes:
        return None
    basis = ["startup_outcome_priors.json"]
    return ResolvedFuturesWeights(
        outcomes=outcomes,
        evidence_basis=basis,
        weight_source=AssumptionSource.REFERENCE,
        model_version="multi_outcome_transition@1.0.0",
    )


def _as_change_models(
    parsed_changes: list[InterventionChangeInput] | None,
) -> list[InterventionChangeResponse]:
    if not parsed_changes:
        return []
    return [InterventionChangeResponse.model_validate(item.model_dump()) for item in parsed_changes]


def _continuous_target_mc_weights(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    scenario_labels: list[str],
    *,
    seed: int,
    parsed_changes: list[InterventionChangeInput] | None = None,
    config: SimulationConfig | None = None,
) -> ResolvedFuturesWeights | None:
    resolved = resolve_simulation_context(goal, evidence)
    if not resolved.priced or resolved.mode != "continuous_target":
        return None
    if resolved.current_value is None or resolved.target_value is None or resolved.periods is None:
        return None

    change_models = _as_change_models(parsed_changes)
    assumptions = (
        apply_parsed_changes_to_assumptions(resolved.assumptions, change_models)
        if change_models
        else resolved.assumptions
    )
    baseline_values = {item.name: item.value for item in resolved.assumptions}
    values = {item.name: item.value for item in assumptions}
    engine = SimulationEngine()
    sim_config = config or SimulationConfig(
        seed=seed, minimum_draws=2000, batch_draws=2000, maximum_draws=4000
    )
    if config is None:
        sim_config = sim_config.model_copy(update={"seed": seed})
    paired = engine.continuous_target(
        current_value=resolved.current_value,
        target_value=resolved.target_value,
        periods=resolved.periods,
        direction=resolved.direction,
        flow=float(baseline_values.get("flow", 0)),
        growth_mean=float(baseline_values.get("growth_mean", 0)),
        growth_volatility=float(baseline_values.get("growth_volatility", 0.03)),
        shock_probability=float(baseline_values.get("shock_probability", 0.02)),
        shock_fraction=float(baseline_values.get("shock_fraction", 0.08)),
        execution_probability=float(baseline_values.get("execution_probability", 0.72)),
        intervention_effect=0.0,
        config=sim_config,
        scenario_flow=float(values.get("flow", 0)) if change_models else None,
        scenario_growth_mean=float(values.get("growth_mean", 0)) if change_models else None,
        scenario_growth_volatility=(
            float(values.get("growth_volatility", 0.03)) if change_models else None
        ),
        scenario_shock_probability=(
            float(values.get("shock_probability", 0.02)) if change_models else None
        ),
        scenario_shock_fraction=(
            float(values.get("shock_fraction", 0.08)) if change_models else None
        ),
    )
    terminal = paired.scenario_outcome if change_models else paired.baseline_outcome
    band_masks = _terminal_band_masks(
        terminal,
        current=resolved.current_value,
        target=resolved.target_value,
        direction=resolved.direction,
    )
    bands = _band_masses(band_masks)
    mapped = _map_labels_to_bands(scenario_labels, bands, domain="continuous")
    if not mapped:
        return None
    outcomes = _definitions_from_map(
        scenario_labels,
        mapped,
        AssumptionSource.REFERENCE,
        terminal_stats=_band_stats(terminal, band_masks, scenario_labels),
    )
    if not outcomes:
        return None
    basis = list(resolved.reference_versions) or ["numerical_transition_model"]
    return ResolvedFuturesWeights(
        outcomes=outcomes,
        evidence_basis=basis,
        weight_source=AssumptionSource.REFERENCE,
        model_version="continuous_target_transition@1.0.0",
    )


def _career_funnel_weights(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    scenario_labels: list[str],
    parsed_changes: list[InterventionChangeInput] | None = None,
) -> ResolvedFuturesWeights | None:
    proposal = proposal_from_goal(goal)
    numeric = build_hiring_numeric_inputs(goal, proposal, evidence)
    if numeric is None:
        return None
    state = aggregate_funnel_from_evidence(evidence)
    reference = load_hiring_reference()
    periods = int(numeric.state.get("periods_remaining") or 1)
    weekly_rate = float(
        numeric.assumptions.get("weekly_application_rate") or reference.weekly_application_rate
    )
    for change in parsed_changes or []:
        if change.metric not in {
            "applications_per_week",
            "weekly_application_rate",
            "linkedin_posts_per_week",
            "sales_calls_per_week",
        }:
            continue
        if change.operation == "set":
            weekly_rate = change.value
        elif change.operation == "subtract":
            weekly_rate = max(0.0, weekly_rate - change.value)
        else:
            weekly_rate += change.value
    expected_apps = weekly_rate * periods

    transforms = numeric.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        p_offer = float(transforms.get("combined_offer_probability") or 0)
    else:
        p_offer = 0.0
    if p_offer <= 0 and state.offers == 0 and expected_apps <= 0:
        return None
    p_response = _reach_stage_prob(expected_apps, reference.stage_rates, 0)
    p_technical = _reach_stage_prob(expected_apps, reference.stage_rates, 3)
    p_final = _reach_stage_prob(expected_apps, reference.stage_rates, 5)
    p_offer_new = _reach_stage_prob(expected_apps, reference.stage_rates, len(STAGE_CHAIN))

    if state.offers > 0:
        p_offer = max(p_offer, min(1.0, 0.2 + state.offers * 0.35))

    bands: dict[BandKey, float] = {
        "offer": min(1.0, max(p_offer, p_offer_new)),
        "final_stage": max(0.0, p_final - min(1.0, max(p_offer, p_offer_new))),
        "technical_stage": max(0.0, p_technical - p_final),
        "screening_stage": max(0.0, p_response - p_technical),
        "no_progress": max(0.0, 1.0 - p_response),
    }
    continuous_bands: dict[BandKey, float] = {
        "target_reached": bands["offer"],
        "meaningful_progress": bands["final_stage"] + bands["technical_stage"],
        "current_trajectory": bands["screening_stage"],
        "downside": bands["no_progress"],
    }
    mapped = _map_labels_to_bands(scenario_labels, continuous_bands, domain="career")
    if not mapped:
        mapped = _map_labels_to_bands(scenario_labels, bands, domain="career_stages")
    if not mapped:
        return None
    outcomes = _definitions_from_map(scenario_labels, mapped, AssumptionSource.REFERENCE)
    if not outcomes:
        return None
    return ResolvedFuturesWeights(
        outcomes=outcomes,
        evidence_basis=[reference.reference_id],
        weight_source=AssumptionSource.REFERENCE,
        model_version="deadline_event_hazard@1.0.0",
    )


def _reach_stage_prob(n_apps: float, rates: dict[str, float], stage_index: int) -> float:
    if n_apps <= 0:
        return 0.0
    p_one = 1.0
    for key in STAGE_CHAIN[: stage_index + 1]:
        p_one *= float(rates[key])
    p_one = min(max(p_one, 0.0), 1.0)
    return float(1.0 - (1.0 - p_one) ** n_apps)


def _band_masses(masks: dict[BandKey, np.ndarray]) -> dict[BandKey, float]:
    masses: dict[BandKey, float] = {
        key: float(np.mean(mask)) if len(mask) else 0.0 for key, mask in masks.items()
    }
    total = sum(masses.values())
    if total <= 0:
        return masses
    return {key: value / total for key, value in masses.items()}


def _terminal_band_masks(
    terminal: np.ndarray,
    *,
    current: float,
    target: float,
    direction: str,
) -> dict[BandKey, np.ndarray]:
    """Assign each simulated terminal value to one band; unmatched draws count as trajectory."""
    n = len(terminal)
    gap = abs(target - current)
    progress_mid = current + 0.5 * (target - current)
    near_current = max(gap * 0.15, abs(current) * 0.05, 1.0)

    if direction == "at_least":
        target_mask = terminal >= target
        progress_mask = (terminal >= progress_mid) & (terminal < target)
        trajectory_mask = np.abs(terminal - current) <= near_current
        downside_mask = terminal < current - near_current * 0.5
    else:
        target_mask = terminal <= target
        progress_mask = (terminal <= progress_mid) & (terminal > target)
        trajectory_mask = np.abs(terminal - current) <= near_current
        downside_mask = terminal > current + near_current * 0.5

    assigned = np.zeros(n, dtype=bool)
    masks: dict[BandKey, np.ndarray] = {}
    ordered: tuple[tuple[BandKey, np.ndarray], ...] = (
        ("target_reached", target_mask),
        ("meaningful_progress", progress_mask),
        ("current_trajectory", trajectory_mask),
        ("downside", downside_mask),
    )
    for key, mask in ordered:
        selected = mask & ~assigned
        masks[key] = selected
        assigned |= selected
    masks["current_trajectory"] = masks["current_trajectory"] | ~assigned
    return masks


def _band_key_for_label(label: str, band_keys: Iterable[str]) -> BandKey | None:
    lowered = label.lower()
    available = set(band_keys)
    for band_key, tokens in _BAND_LABEL_TOKENS.items():
        if band_key in available and any(token in lowered for token in tokens):
            return band_key
    return None


def _map_labels_to_bands(
    labels: list[str],
    bands: Mapping[BandKey, float],
    *,
    domain: str,
) -> dict[str, float]:
    mapped: dict[str, float] = {}
    for label in labels:
        band_key = _band_key_for_label(label, bands)
        if band_key is not None:
            mapped[label] = mapped.get(label, 0.0) + bands[band_key]
    if not mapped:
        return {}
    total = sum(mapped.values())
    if total <= 0:
        return {}
    return {label: weight / total for label, weight in mapped.items()}


def _definitions_from_map(
    labels: list[str],
    weights: dict[str, float],
    source: AssumptionSource,
    *,
    terminal_stats: dict[str, tuple[float, float, float]] | None = None,
) -> list[ScenarioDefinition]:
    outcomes: list[ScenarioDefinition] = []
    for label in labels:
        weight = weights.get(label)
        if weight is None:
            continue
        stats = terminal_stats.get(label) if terminal_stats else None
        outcomes.append(
            ScenarioDefinition(
                label=label,
                weight=weight,
                weight_source=source,
                median=stats[1] if stats else None,
                p10=stats[0] if stats else None,
                p90=stats[2] if stats else None,
                downside="downside" in label.lower(),
            )
        )
    return outcomes


def _band_stats(
    terminal: np.ndarray,
    masks: dict[BandKey, np.ndarray],
    labels: list[str],
) -> dict[str, tuple[float, float, float]]:
    """Quantiles of the simulated terminal values that fall inside each label's band."""
    stats: dict[str, tuple[float, float, float]] = {}
    for label in labels:
        band_key = _band_key_for_label(label, masks)
        if band_key is None:
            continue
        members = terminal[masks[band_key]]
        if not len(members):
            continue
        p10, p50, p90 = np.percentile(members, [10, 50, 90])
        stats[label] = (float(p10), float(p50), float(p90))
    return stats
