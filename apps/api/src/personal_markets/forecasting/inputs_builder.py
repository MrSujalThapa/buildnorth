from __future__ import annotations

from datetime import datetime
from typing import Any

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.finance import build_finance_numeric_inputs, is_finance_goal
from personal_markets.forecasting.hiring import build_hiring_numeric_inputs, is_hiring_goal
from personal_markets.forecasting.running import build_running_numeric_inputs, is_running_goal
from personal_markets.forecasting.startup import build_startup_numeric_inputs, is_startup_goal
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


def build_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    """Map validated goal/evidence into typed numerical inputs for baseline pricing.

    `now` prices the goal as of an earlier moment, e.g. when replaying evidence history.
    """
    from personal_markets.forecasting.compiler import spec_from_mapping
    from personal_markets.forecasting.composition import composition_numeric_inputs

    composed_spec = spec_from_mapping(goal.model_requirements.get("forecast_spec"))
    if composed_spec is not None:
        return composition_numeric_inputs(goal, evidence, overrides=overrides, now=now)
    # Ordered most specific first. Finance matches any money-denominated target, so it
    # must run after the domains that also happen to be measured in dollars.
    if is_hiring_goal(goal, proposal):
        return build_hiring_numeric_inputs(goal, proposal, evidence, overrides=overrides, now=now)
    if is_running_goal(goal, proposal):
        return build_running_numeric_inputs(goal, proposal, evidence, overrides=overrides, now=now)
    if is_startup_goal(goal, proposal):
        return build_startup_numeric_inputs(goal, proposal, evidence, overrides=overrides, now=now)
    if is_finance_goal(goal, proposal):
        return build_finance_numeric_inputs(goal, proposal, evidence, overrides=overrides, now=now)
    return composition_numeric_inputs(goal, evidence, overrides=overrides, now=now)


def proposal_from_goal(goal: GoalContract) -> GoalArchitectProposal:
    definition = goal.success_definition
    metric = str(definition.get("metric") or definition.get("event") or "target")
    target = definition.get("target") or definition.get("amount") or definition.get("value") or ""
    operator = str(definition.get("operator") or "==")
    family = _infer_model_family(goal)
    constraints = goal.resource_constraints
    hours = constraints.hours_per_week if constraints else None
    return GoalArchitectProposal(
        ready_to_commit=True,
        title=goal.title,
        goal_type=goal.goal_type.value,
        success_metric=metric,
        success_operator=operator,
        success_target=str(target),
        deadline=goal.deadline.date().isoformat(),
        state_dimensions=list(goal.state_dimensions),
        hours_per_week=hours,
        model_family_compatibility=family,
    )


def _infer_model_family(goal: GoalContract) -> str:
    blob = f"{goal.title} {goal.success_definition} {' '.join(goal.state_dimensions)}".lower()
    if "net_worth" in blob or "million" in blob:
        return "exploratory_finance"
    if any(token in blob for token in ("offer", "swe", "fde", "interview", "hiring")):
        return "exploratory_hiring"
    if goal.goal_type == GoalType.THRESHOLD and any(
        token in blob for token in ("run", "10k", "race", "marathon")
    ):
        return "exploratory_running"
    if any(token in blob for token in ("startup", "mrr", "seed", "fundraising")):
        return "exploratory_startup"
    return "exploratory_general"
