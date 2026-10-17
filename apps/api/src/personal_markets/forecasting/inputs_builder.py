from __future__ import annotations

from typing import Any

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.finance import build_finance_numeric_inputs, is_finance_goal
from personal_markets.forecasting.hiring import build_hiring_numeric_inputs, is_hiring_goal
from personal_markets.forecasting.running import build_running_numeric_inputs, is_running_goal
from personal_markets.forecasting.startup import build_startup_numeric_inputs, is_startup_goal
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import GoalArchitectProposal


def build_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
) -> NumericInputs | None:
    """Map validated goal/evidence into typed numerical inputs for baseline pricing."""
    # Ordered most specific first. Finance matches any money-denominated target, so it
    # must run after the domains that also happen to be measured in dollars.
    if is_hiring_goal(goal, proposal):
        return build_hiring_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    if is_running_goal(goal, proposal):
        return build_running_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    if is_startup_goal(goal, proposal):
        return build_startup_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    if is_finance_goal(goal, proposal):
        return build_finance_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    return None
