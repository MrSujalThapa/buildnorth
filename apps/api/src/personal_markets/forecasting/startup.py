from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.targets import resolve_target_number
from personal_markets.ports import GoalArchitectProposal

REFERENCE_ID = "startup_outcome_priors.json"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[5]


@dataclass(frozen=True, slots=True)
class StartupState:
    mrr: float | None = None
    revenue: float | None = None
    revenue_growth_rate: float | None = None
    users: float | None = None
    retention_rate: float | None = None
    runway_months: float | None = None
    burn_monthly: float | None = None
    team_size: float | None = None
    term_sheet: bool = False
    fundraising_conversations: int = 0
    product_launches: int = 0


@dataclass(frozen=True, slots=True)
class StartupReference:
    outcome_taxonomy: tuple[str, ...]
    base_weights: dict[str, float]
    signal_adjustments: dict[str, dict[str, float]]
    seed_round_hazard: dict[str, float]
    reference_id: str
    version: str
    limitations: tuple[str, ...]


def load_startup_reference(root: Path | None = None) -> StartupReference:
    path = (root or _repo_root() / "data" / "reference") / REFERENCE_ID
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StartupReference(
        outcome_taxonomy=tuple(payload.get("outcome_taxonomy") or []),
        base_weights={str(k): float(v) for k, v in (payload.get("base_weights") or {}).items()},
        signal_adjustments={
            str(key): {str(k): float(v) for k, v in value.items()}
            for key, value in (payload.get("signal_adjustments") or {}).items()
        },
        seed_round_hazard={
            str(k): float(v) for k, v in (payload.get("seed_round_hazard") or {}).items()
        },
        reference_id=REFERENCE_ID,
        version=str(payload.get("version") or "unknown"),
        limitations=tuple(payload.get("limitations") or []),
    )


def is_startup_goal(goal: GoalContract, proposal: GoalArchitectProposal | None = None) -> bool:
    blob = " ".join(
        [
            goal.title,
            str(goal.success_definition),
            " ".join(goal.state_dimensions),
            proposal.success_metric if proposal else "",
        ]
    ).lower()
    tokens = (
        "startup",
        "seed",
        "mrr",
        "fundraise",
        "runway",
        "revenue",
        "term sheet",
        "founder",
    )
    return any(token in blob for token in tokens)


def startup_goal_kind(goal: GoalContract) -> str:
    if goal.goal_type is GoalType.MULTI_OUTCOME:
        return "multi_outcome"
    metric = str(goal.success_definition.get("metric") or "").lower()
    blob = goal.title.lower()
    if "seed" in metric or "seed" in blob or "raise" in blob:
        return "deadline_event"
    if "mrr" in metric or "revenue" in metric:
        if goal.goal_type is GoalType.THRESHOLD:
            return "threshold"
        if goal.goal_type is GoalType.CONTINUOUS_TARGET:
            return "continuous_target"
    return "multi_outcome"


def aggregate_startup_from_evidence(evidence: list[NormalizedEvidence]) -> StartupState:
    state = StartupState()
    for item in evidence:
        metric = item.metric.lower()
        summary = item.summary.lower()
        value = item.numeric_value
        if metric in {"mrr", "monthly_recurring_revenue"} and value is not None:
            state = replace(state, mrr=float(value))
        elif metric in {"revenue", "monthly_revenue"} and value is not None:
            state = replace(state, revenue=float(value))
        elif metric in {"revenue_growth_rate", "growth_rate"} and value is not None:
            state = replace(state, revenue_growth_rate=float(value))
        elif metric in {"users", "customers", "active_users"} and value is not None:
            state = replace(state, users=float(value))
        elif metric in {"retention_rate", "retention"} and value is not None:
            state = replace(state, retention_rate=float(value))
        elif metric in {"runway_months", "runway"} and value is not None:
            state = replace(state, runway_months=float(value))
        elif metric in {"burn_monthly", "monthly_burn", "burn"} and value is not None:
            state = replace(state, burn_monthly=float(value))
        elif metric in {"team_size", "employees"} and value is not None:
            state = replace(state, team_size=float(value))
        elif "term sheet" in summary or metric == "term_sheet":
            state = replace(state, term_sheet=True)
        elif "fundraising" in summary or metric == "fundraising_conversation":
            state = replace(
                state,
                fundraising_conversations=state.fundraising_conversations + 1,
            )
        elif "launch" in summary or metric == "product_launch":
            state = replace(state, product_launches=state.product_launches + 1)
    return state


def apply_startup_overrides(state: StartupState, overrides: dict[str, Any] | None) -> StartupState:
    if not overrides:
        return state
    updated = state
    if "mrr" in overrides:
        updated = replace(updated, mrr=float(overrides["mrr"]))
    if "revenue" in overrides:
        updated = replace(updated, revenue=float(overrides["revenue"]))
    if "revenue_growth_rate" in overrides:
        updated = replace(updated, revenue_growth_rate=float(overrides["revenue_growth_rate"]))
    if "users" in overrides:
        updated = replace(updated, users=float(overrides["users"]))
    if "retention_rate" in overrides:
        updated = replace(updated, retention_rate=float(overrides["retention_rate"]))
    if "runway_months" in overrides:
        updated = replace(updated, runway_months=float(overrides["runway_months"]))
    if "burn_monthly" in overrides:
        updated = replace(updated, burn_monthly=float(overrides["burn_monthly"]))
    if "team_size" in overrides:
        updated = replace(updated, team_size=float(overrides["team_size"]))
    if "term_sheet" in overrides:
        updated = replace(updated, term_sheet=bool(overrides["term_sheet"]))
    if "fundraising_conversations" in overrides:
        updated = replace(
            updated, fundraising_conversations=int(overrides["fundraising_conversations"])
        )
    return updated


def derive_outcome_weights(
    state: StartupState, reference: StartupReference | None = None
) -> dict[str, float]:
    ref = reference or load_startup_reference()
    weights = dict(ref.base_weights)
    if state.term_sheet:
        _apply_adjustment(weights, ref.signal_adjustments.get("term_sheet_received", {}))
    if state.fundraising_conversations:
        _apply_adjustment(weights, ref.signal_adjustments.get("fundraising_conversation", {}))
    if state.runway_months is not None and state.runway_months < 3:
        _apply_adjustment(weights, ref.signal_adjustments.get("runway_under_3_months", {}))
    if state.revenue_growth_rate is not None and state.revenue_growth_rate > 0:
        _apply_adjustment(weights, ref.signal_adjustments.get("positive_revenue_growth", {}))
    return _normalize_weights(weights)


def build_startup_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    if not is_startup_goal(goal, proposal):
        return None
    state = aggregate_startup_from_evidence(evidence)
    state = apply_startup_overrides(state, overrides)
    ref = load_startup_reference()
    kind = startup_goal_kind(goal)

    if kind == "multi_outcome" or goal.goal_type is GoalType.MULTI_OUTCOME:
        if not _has_startup_signal(state):
            return None
        weights = derive_outcome_weights(state, ref)
        target = str(
            goal.success_definition.get("target")
            or goal.success_definition.get("metric")
            or ""
        )
        if target not in weights:
            for candidate in (
                "raise_external_funding",
                "high_growth_trajectory",
                "bootstrap_sustainable",
            ):
                if candidate in weights:
                    target = candidate
                    break
        transforms = cast(
            dict[str, Any],
            {
                "startup_state": _state_dict(state),
                "outcome_weights": weights,
                "reference_version": ref.version,
            },
        )
        return NumericInputs(
            state={"outcome_weights": weights, "pricing_transforms": transforms},
            assumptions={"outcome_weights": weights},
            assumption_sources={"outcome_weights": "REFERENCE"},
        )

    if kind == "deadline_event":
        if not _has_startup_signal(state):
            return None
        logit = float(ref.seed_round_hazard.get("baseline_logit", -2.2))
        if state.term_sheet:
            logit += float(ref.seed_round_hazard.get("term_sheet_logit_boost", 1.4))
        if state.runway_months is not None and state.runway_months < 3:
            logit += float(ref.seed_round_hazard.get("runway_months_under_3_logit_penalty", -0.8))
        if state.mrr is not None:
            logit += float(ref.seed_round_hazard.get("mrr_logit_per_1k", 0.02)) * (
                state.mrr / 1000.0
            )
        clock = now or datetime.now(UTC)
        periods = max(1, math.ceil((goal.deadline - clock).total_seconds() / 604800))
        transforms = cast(
            dict[str, Any],
            {
                "startup_state": _state_dict(state),
                "seed_hazard_logit": logit,
                "reference_version": ref.version,
            },
        )
        return NumericInputs(
            state={
                "baseline_logits": [logit] * periods,
                "periods_remaining": periods,
                "pricing_transforms": transforms,
            },
            assumption_sources={"baseline_logits": "REFERENCE"},
        )

    if kind == "continuous_target" and state.mrr is not None:
        from personal_markets.forecasting.finance import (
            FinanceState,
            finance_state_to_numeric_inputs,
        )

        contribution = 0.0
        if state.revenue_growth_rate is not None:
            contribution = state.mrr * state.revenue_growth_rate
        finance = FinanceState(net_worth=state.mrr, monthly_contribution=contribution)
        return finance_state_to_numeric_inputs(goal, finance, now=now)

    if kind == "threshold" and state.mrr is not None:
        resolved_target = resolve_target_number(goal)
        if resolved_target is None:
            return None
        target_value = resolved_target
        clock = now or datetime.now(UTC)
        periods = max(1, math.ceil((goal.deadline - clock).total_seconds() / 604800))
        current = state.mrr
        growth = state.revenue_growth_rate or 0.0
        projected = current * (1 + growth) ** (periods / 4.0)
        transforms = cast(
            dict[str, Any],
            {
                "startup_state": _state_dict(state),
                "projected_mrr": projected,
                "reference_version": ref.version,
            },
        )
        return NumericInputs(
            state={
                "current_value": projected,
                "target_value": target_value,
                "periods": periods,
                "direction": "at_least",
                "pricing_transforms": transforms,
            },
            assumptions={
                "trend": (projected - current) / max(1, periods) * 7,
                "measurement_noise": max(50.0, current * 0.05),
                "adherence": 1.0,
            },
            assumption_sources={
                "trend": "REAL_USER_EVIDENCE",
                "measurement_noise": "REFERENCE",
                "adherence": "REFERENCE",
            },
        )

    return None


def futures_outcome_weights(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    *,
    scenario_labels: list[str] | None = None,
) -> tuple[dict[str, float] | None, str | None]:
    """Map Possible Futures labels to numerical weights when startup evidence exists."""
    if not is_startup_goal(goal):
        return None, "not a startup goal"
    state = aggregate_startup_from_evidence(evidence)
    if not _has_startup_signal(state):
        return None, "insufficient startup evidence for defensible weights"
    ref = load_startup_reference()
    derived = derive_outcome_weights(state, ref)
    if not scenario_labels:
        return derived, None
    mapped: dict[str, float] = {}
    for label in scenario_labels:
        key = _map_label_to_outcome(label, ref.outcome_taxonomy)
        if key:
            mapped[label] = derived.get(key, 0.0)
    if not mapped:
        return None, "no scenario labels matched the startup outcome taxonomy"
    total = sum(mapped.values())
    if total <= 0:
        return None, "scenario labels matched but weight mass was zero"
    normalized = {label: weight / total for label, weight in mapped.items()}
    return normalized, None


def _has_startup_signal(state: StartupState) -> bool:
    return any(
        [
            state.mrr is not None,
            state.revenue is not None,
            state.runway_months is not None,
            state.term_sheet,
            state.fundraising_conversations > 0,
            state.product_launches > 0,
        ]
    )


def _state_dict(state: StartupState) -> dict[str, Any]:
    return {
        "mrr": state.mrr,
        "revenue": state.revenue,
        "revenue_growth_rate": state.revenue_growth_rate,
        "runway_months": state.runway_months,
        "term_sheet": state.term_sheet,
        "fundraising_conversations": state.fundraising_conversations,
        "product_launches": state.product_launches,
    }


def _apply_adjustment(weights: dict[str, float], adjustment: dict[str, float]) -> None:
    for key, delta in adjustment.items():
        weights[key] = weights.get(key, 0.0) + delta


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    clipped = {key: max(0.0, value) for key, value in weights.items()}
    total = sum(clipped.values())
    if total <= 0:
        return clipped
    return {key: value / total for key, value in clipped.items()}


def _map_label_to_outcome(label: str, taxonomy: tuple[str, ...]) -> str | None:
    lowered = label.lower()
    mapping = {
        "shut": "shutdown_before_traction",
        "shutdown": "shutdown_before_traction",
        "side project": "side_project",
        "bootstrap": "bootstrap_sustainable",
        "sustainable": "bootstrap_sustainable",
        "raise": "raise_external_funding",
        "funding": "raise_external_funding",
        "seed": "raise_external_funding",
        "high growth": "high_growth_trajectory",
        "growth": "high_growth_trajectory",
        "other": "other",
    }
    for token, outcome in mapping.items():
        if token in lowered and outcome in taxonomy:
            return outcome
    return "other" if "other" in taxonomy else None
