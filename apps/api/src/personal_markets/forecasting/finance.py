from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.requirements import (
    StateRequirement,
    StateResolution,
    resolve_state,
)
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import (
    resolve_target_number,
    target_direction,
    target_is_monetary,
)
from personal_markets.ports import GoalArchitectProposal

REFERENCE_ID = "net_worth_assumptions.json"
BASELINE_MC_DRAWS = 5000
BASELINE_MC_SEED = 42


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[5]


@dataclass(frozen=True, slots=True)
class FinanceState:
    net_worth: float | None = None
    liquid_assets: float | None = None
    liabilities: float | None = None
    monthly_income: float | None = None
    monthly_expenses: float | None = None
    monthly_contribution: float | None = None
    last_observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FinanceReferenceDefaults:
    annual_return_mean: float
    annual_return_volatility: float
    periods_per_year: int
    shock_probability_per_period: float
    shock_fraction: float
    reference_id: str
    version: str
    limitations: tuple[str, ...]


def load_finance_reference(root: Path | None = None) -> FinanceReferenceDefaults:
    path = (root or _repo_root() / "data" / "reference") / REFERENCE_ID
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults") or {}
    return FinanceReferenceDefaults(
        annual_return_mean=float(defaults.get("annual_return_mean", 0.07)),
        annual_return_volatility=float(defaults.get("annual_return_volatility", 0.15)),
        periods_per_year=int(defaults.get("periods_per_year", 12)),
        shock_probability_per_period=float(defaults.get("shock_probability_per_period", 0.02)),
        shock_fraction=float(defaults.get("shock_fraction", 0.08)),
        reference_id=REFERENCE_ID,
        version=str(payload.get("version") or "unknown"),
        limitations=tuple(payload.get("limitations") or []),
    )


def is_finance_goal(goal: GoalContract, proposal: GoalArchitectProposal | None = None) -> bool:
    blob = " ".join(
        [
            goal.title,
            str(goal.success_definition),
            " ".join(goal.state_dimensions),
            proposal.success_metric if proposal else "",
        ]
    ).lower()
    tokens = (
        "net worth",
        "net_worth",
        "wealth",
        "million",
        "finance",
        "liquid_assets",
        "savings",
        "portfolio",
    )
    metric = str(goal.success_definition.get("metric") or "").lower()
    if metric == "net_worth" or any(token in blob for token in tokens):
        return True
    # Nouns for a pot of money are unbounded; the target's dimension is not.
    return target_is_monetary(goal)


def finance_requirements(goal: GoalContract | None = None) -> tuple[StateRequirement, ...]:
    """State variables the wealth-accumulation model consumes.

    The balance label is taken from the goal's own declared success metric so the
    prompt shown to the user matches the goal they wrote, rather than a fixed phrase.
    """
    metric = ""
    if goal is not None:
        metric = str(goal.success_definition.get("metric") or "").strip()
    balance_label = metric or "Current balance"
    return (
        StateRequirement(
            key="current_balance",
            label=balance_label,
            unit="currency",
            why="The simulation has to start from the amount you hold today.",
            aliases=(
                "net_worth",
                "liquid_assets",
                "liquid",
                "balance",
                "current_balance",
                "account_balance",
                metric,
            ),
            example="4200",
            suggested_sources=("bank or brokerage export", "a spreadsheet column", "manual entry"),
        ),
        StateRequirement(
            key="monthly_contribution",
            label="Monthly contribution",
            unit="currency/month",
            why="Recurring contributions drive most of the progress toward the target.",
            aliases=(
                "monthly_contribution",
                "savings_contribution",
                "contribution",
                "monthly_savings",
                "monthly_deposit",
                "recurring_transfer",
            ),
            derived_from=(("monthly_income", "monthly_expenses"),),
            example="600",
            suggested_sources=("recurring transfers", "a savings history export", "manual entry"),
        ),
        StateRequirement(
            key="monthly_income",
            label="Monthly take-home income",
            unit="currency/month",
            why="Used with expenses to infer how much you can save each month.",
            aliases=("monthly_income", "income_monthly", "take_home_income", "net_income"),
            required=False,
            example="5400",
        ),
        StateRequirement(
            key="monthly_expenses",
            label="Monthly expenses",
            unit="currency/month",
            why="Used with income to infer how much you can save each month.",
            aliases=("monthly_expenses", "expenses_monthly", "spending", "monthly_spend"),
            required=False,
            example="4600",
        ),
        StateRequirement(
            key="liabilities",
            label="Debt / liabilities",
            unit="currency",
            why="Subtracted from assets when the goal is stated as net worth.",
            aliases=("liabilities", "debt", "total_debt", "loan_balance"),
            required=False,
        ),
    )


def resolve_finance_state(
    evidence: list[NormalizedEvidence],
    *,
    goal: GoalContract | None = None,
    overrides: dict[str, Any] | None = None,
) -> tuple[FinanceState, StateResolution]:
    """Resolve evidence onto the declared finance vocabulary."""
    resolution = resolve_state(finance_requirements(goal), evidence, overrides=overrides)
    observed = [item.observed_at for item in evidence if item.observed_at is not None]
    balance = resolution.resolved.get("current_balance")
    # A net-worth figure is already net of liabilities; any other balance is gross,
    # so liabilities are subtracted from it downstream.
    matched = (balance.matched_metric or "") if balance else ""
    is_net = "net_worth" in matched.lower().replace(" ", "_")
    return (
        FinanceState(
            net_worth=balance.value if balance and is_net else None,
            liquid_assets=balance.value if balance and not is_net else None,
            liabilities=resolution.value("liabilities"),
            monthly_income=resolution.value("monthly_income"),
            monthly_expenses=resolution.value("monthly_expenses"),
            monthly_contribution=resolution.value("monthly_contribution"),
            last_observed_at=max(observed) if observed else None,
        ),
        resolution,
    )


def aggregate_finance_from_evidence(
    evidence: list[NormalizedEvidence],
    *,
    goal: GoalContract | None = None,
    now: datetime | None = None,
) -> FinanceState:
    _ = now
    state, _resolution = resolve_finance_state(evidence, goal=goal)
    return state


def resolve_current_net_worth(state: FinanceState) -> float | None:
    if state.net_worth is not None:
        return state.net_worth
    if state.liquid_assets is not None:
        liabilities = state.liabilities or 0.0
        return state.liquid_assets - liabilities
    return None


def resolve_monthly_flow(state: FinanceState) -> float | None:
    if state.monthly_contribution is not None:
        return state.monthly_contribution
    if state.monthly_income is not None and state.monthly_expenses is not None:
        return state.monthly_income - state.monthly_expenses
    return None


def apply_finance_overrides(
    state: FinanceState, overrides: dict[str, Any] | None
) -> FinanceState:
    if not overrides:
        return state
    updated = state
    if "current_balance" in overrides:
        updated = replace(updated, liquid_assets=float(overrides["current_balance"]))
    if "net_worth" in overrides:
        updated = replace(updated, net_worth=float(overrides["net_worth"]))
    if "liquid_assets" in overrides:
        updated = replace(updated, liquid_assets=float(overrides["liquid_assets"]))
    if "liabilities" in overrides:
        updated = replace(updated, liabilities=float(overrides["liabilities"]))
    if "monthly_income" in overrides:
        updated = replace(updated, monthly_income=float(overrides["monthly_income"]))
    if "monthly_expenses" in overrides:
        updated = replace(updated, monthly_expenses=float(overrides["monthly_expenses"]))
    if "monthly_contribution" in overrides:
        updated = replace(updated, monthly_contribution=float(overrides["monthly_contribution"]))
    return updated


def periods_until_deadline(goal: GoalContract, now: datetime | None = None) -> int:
    clock = now or datetime.now(UTC)
    months = max(1, math.ceil((goal.deadline - clock).total_seconds() / (86400.0 * 30.4375)))
    return months


def target_amount(goal: GoalContract) -> float | None:
    return resolve_target_number(goal)


def finance_state_to_numeric_inputs(
    goal: GoalContract,
    state: FinanceState,
    *,
    reference: FinanceReferenceDefaults | None = None,
    assumption_overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    ref = reference or load_finance_reference()
    current = resolve_current_net_worth(state)
    target = target_amount(goal)
    flow = resolve_monthly_flow(state)
    if current is None or target is None or flow is None:
        return None

    periods = periods_until_deadline(goal, now)
    direction = _goal_direction(goal)
    overrides_map = assumption_overrides or {}
    annual_mean = float(overrides_map.get("annual_return_mean", ref.annual_return_mean))
    annual_vol = float(overrides_map.get("annual_return_volatility", ref.annual_return_volatility))
    period_mean = annual_mean / ref.periods_per_year
    period_vol = annual_vol / math.sqrt(ref.periods_per_year)
    shock_probability = float(
        overrides_map.get("shock_probability_per_period", ref.shock_probability_per_period)
    )
    shock_fraction = float(overrides_map.get("shock_fraction", ref.shock_fraction))

    transforms = {
        "finance_state": {
            "current_value": current,
            "target_value": target,
            "monthly_flow": flow,
            "periods": periods,
            "direction": direction,
        },
        "reference_version": ref.version,
    }
    assumption_sources = {
        "annual_return_mean": "REFERENCE",
        "annual_return_volatility": "REFERENCE",
        "shock_probability_per_period": "REFERENCE",
        "shock_fraction": "REFERENCE",
        "monthly_flow": "REAL_USER_EVIDENCE",
    }
    if assumption_overrides:
        for key in assumption_overrides:
            assumption_sources[key] = "USER_ASSUMPTION"

    return NumericInputs(
        state={
            "current_value": current,
            "target_value": target,
            "periods": periods,
            "direction": direction,
            "pricing_transforms": transforms,
        },
        assumptions={
            "return_distribution": {
                "flow": flow,
                "growth_mean": period_mean,
                "growth_volatility": period_vol,
                "shock_probability": shock_probability,
                "shock_fraction": shock_fraction,
            },
            "annual_return_mean": annual_mean,
            "annual_return_volatility": annual_vol,
        },
        assumption_sources=assumption_sources,
    )


def build_finance_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    if not is_finance_goal(goal, proposal):
        return None
    state, _resolution = resolve_finance_state(evidence, goal=goal)
    state = apply_finance_overrides(state, overrides)
    assumption_overrides = None
    if overrides:
        assumption_overrides = {
            key: overrides[key]
            for key in (
                "annual_return_mean",
                "annual_return_volatility",
                "shock_probability_per_period",
                "shock_fraction",
            )
            if key in overrides
        }
    numeric = finance_state_to_numeric_inputs(
        goal, state, assumption_overrides=assumption_overrides, now=now
    )
    if numeric is None:
        return None
    return numeric


def monte_carlo_success_probability(
    *,
    current_value: float,
    target_value: float,
    periods: int,
    direction: str,
    flow: float,
    growth_mean: float,
    growth_volatility: float,
    shock_probability: float,
    shock_fraction: float,
    seed: int = BASELINE_MC_SEED,
    draws: int = BASELINE_MC_DRAWS,
) -> tuple[float, dict[str, Any]]:
    rng = np.random.default_rng(seed)
    returns = rng.standard_t(df=5, size=(draws, periods))
    returns = growth_mean + returns * growth_volatility / np.sqrt(5 / 3)
    shocks = rng.random((draws, periods)) < shock_probability
    values = np.full(draws, current_value, dtype=float)
    for period in range(periods):
        shock = np.where(shocks[:, period], shock_fraction, 0.0)
        values = values * (1 + returns[:, period] - shock)
        values += flow
    success = values >= target_value if direction == "at_least" else values <= target_value
    probability = float(np.mean(success))
    error = float(np.sqrt(probability * (1 - probability) / draws))
    return probability, {
        "n_draws": draws,
        "seed": seed,
        "achieved_mc_error": error,
        "terminal_mean": float(np.mean(values)),
        "terminal_p10": float(np.quantile(values, 0.1)),
        "terminal_p90": float(np.quantile(values, 0.9)),
    }


def price_from_numeric_inputs(inputs: NumericInputs) -> tuple[float | None, dict[str, Any]]:
    current = inputs.state.get("current_value")
    target = inputs.state.get("target_value")
    periods = inputs.state.get("periods")
    direction = inputs.state.get("direction", "at_least")
    distribution = inputs.assumptions.get("return_distribution")
    if current is None or target is None or periods is None:
        return None, {}
    if not isinstance(distribution, dict):
        return None, {}
    try:
        current_value = float(current)
        target_value = float(target)
        period_count = int(periods)
        flow = float(distribution["flow"])
        growth_mean = float(distribution["growth_mean"])
        growth_volatility = float(distribution["growth_volatility"])
        shock_probability = float(distribution.get("shock_probability", 0.0))
        shock_fraction = float(distribution.get("shock_fraction", 0.0))
    except (KeyError, TypeError, ValueError):
        return None, {}
    probability, diagnostics = monte_carlo_success_probability(
        current_value=current_value,
        target_value=target_value,
        periods=period_count,
        direction=str(direction),
        flow=flow,
        growth_mean=growth_mean,
        growth_volatility=growth_volatility,
        shock_probability=shock_probability,
        shock_fraction=shock_fraction,
    )
    transforms = inputs.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        transforms = {**transforms, "mc_diagnostics": diagnostics}
    else:
        transforms = {"mc_diagnostics": diagnostics}
    return probability, transforms


def _goal_direction(goal: GoalContract) -> str:
    return target_direction(goal, default="at_least")
