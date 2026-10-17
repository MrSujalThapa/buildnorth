from __future__ import annotations

from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.domain import (
    ResourceBudget,
    ResourceUsage,
    StructuredIntervention,
)


def budget_from_goal(goal: GoalContract) -> ResourceBudget:
    constraints = goal.resource_constraints
    if constraints is None:
        return ResourceBudget()
    return ResourceBudget(
        hours_per_week=float(constraints.hours_per_week or 0),
        money_per_month=float(constraints.budget_amount or 0),
    )


def evaluate_resource_usage(
    intervention: StructuredIntervention | None,
    budget: ResourceBudget,
) -> ResourceUsage:
    if intervention is None:
        return ResourceUsage(within_budget=True)

    cost = intervention.cost
    usage = ResourceUsage(
        hours_per_week=cost.hours_per_week,
        money_per_month=cost.money,
    )
    notes: list[str] = []
    within = True
    if budget.hours_per_week > 0 and cost.hours_per_week > budget.hours_per_week:
        within = False
        notes.append(
            f"Plan requires {cost.hours_per_week:g}h/week but budget allows "
            f"{budget.hours_per_week:g}h/week."
        )
    if budget.money_per_month > 0 and cost.money > budget.money_per_month:
        within = False
        notes.append(
            f"Plan requires {cost.money:g}/month but budget allows "
            f"{budget.money_per_month:g}/month."
        )
    return usage.model_copy(update={"within_budget": within, "over_budget_notes": notes})


def execution_scale_for_budget(
    execution_probability: float,
    usage: ResourceUsage,
    budget: ResourceBudget,
) -> tuple[float, list[str]]:
    if usage.within_budget or budget.hours_per_week <= 0:
        return execution_probability, []
    ratio = min(1.0, budget.hours_per_week / max(usage.hours_per_week, 1e-9))
    scaled = execution_probability * ratio
    note = (
        f"Execution probability scaled from {execution_probability:.2f} to {scaled:.2f} "
        f"because required hours exceed the declared weekly budget."
    )
    return scaled, [note]


def opportunity_cost_messages(
    intervention: StructuredIntervention | None,
    usage: ResourceUsage,
) -> list[str]:
    if intervention is None:
        return []
    costs: list[str] = []
    cost = intervention.cost
    if cost.hours_per_week:
        costs.append(f"{cost.hours_per_week:g} hours/week required")
    if cost.money:
        costs.append(f"{cost.money:g} monetary units/month committed")
    costs.extend(usage.over_budget_notes)
    return costs
