"""Report what a goal still needs before it can be priced.

`build_numeric_inputs` answers "can I price this?" with a bare ``None``. That is
enough for the engine but useless to a person: it cannot distinguish "this goal is
outside our models" from "we just need your current balance". This module routes a
goal to the state vocabulary its model family consumes and reports the difference.
"""

from __future__ import annotations

from typing import Any

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.finance import finance_requirements, is_finance_goal
from personal_markets.forecasting.hiring import is_hiring_goal
from personal_markets.forecasting.requirements import (
    PriceabilityReport,
    StateRequirement,
    build_report,
    resolve_state,
)
from personal_markets.forecasting.running import is_running_goal
from personal_markets.forecasting.startup import is_startup_goal
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import resolve_target
from personal_markets.ports import GoalArchitectProposal


def hiring_requirements() -> tuple[StateRequirement, ...]:
    return (
        StateRequirement(
            key="applications",
            label="Applications submitted so far",
            unit="count",
            why="The funnel starts from how many applications you have actually sent.",
            aliases=(
                "applications",
                "applications_submitted",
                "application_count",
                "applications_sent",
                "job_applications",
                "job_applications_submitted",
                "apps_submitted",
            ),
            example="24",
            suggested_sources=(
                "an application tracker",
                "your email or calendar",
                "manual entry",
            ),
        ),
        StateRequirement(
            key="responses",
            label="Replies or screens received",
            unit="count",
            why="Observed conversions anchor the funnel to your results, not averages.",
            aliases=("responses", "replies", "recruiter_responses", "callbacks", "screens"),
            required=False,
            example="5",
        ),
        StateRequirement(
            key="practice_hours",
            label="Interview preparation hours",
            unit="hours",
            why="Preparation is the state variable most interview actions move.",
            aliases=("practice_hours", "prep_hours", "interview_prep_hours", "study_hours"),
            required=False,
            example="20",
        ),
    )


def running_requirements() -> tuple[StateRequirement, ...]:
    return (
        StateRequirement(
            key="recent_race_time",
            label="A recent timed run or race result",
            unit="seconds",
            why="Your projected finish time is fitted to timed efforts you have actually run.",
            aliases=(
                "race_time_seconds",
                "run_time_seconds",
                "10k_time_seconds",
                "5k_time_seconds",
                "finish_time",
                "time_trial",
            ),
            example="3120",
            suggested_sources=("a training log", "a watch or Strava export", "manual entry"),
        ),
        StateRequirement(
            key="weekly_distance_km",
            label="Current weekly training volume",
            unit="km/week",
            why="Training volume drives the improvement trend and injury/adherence risk.",
            aliases=("weekly_distance_km", "weekly_distance", "weekly_mileage", "volume_km"),
            required=False,
            example="35",
        ),
    )


def startup_requirements() -> tuple[StateRequirement, ...]:
    return (
        StateRequirement(
            key="mrr",
            label="Current monthly recurring revenue",
            unit="currency/month",
            why="Revenue level is the state the growth model advances each period.",
            aliases=("mrr", "monthly_recurring_revenue", "revenue_monthly"),
            example="9000",
        ),
        StateRequirement(
            key="revenue_growth_rate",
            label="Recent revenue growth rate",
            unit="fraction/month",
            why="Growth rate determines the trajectory toward the revenue target.",
            aliases=("revenue_growth_rate", "growth_rate", "mom_growth"),
            required=False,
            example="0.08",
        ),
    )


def composition_requirements(spec: dict[str, Any]) -> tuple[StateRequirement, ...]:
    requirements: list[StateRequirement] = []
    primitives = spec.get("primitives") or []
    first = primitives[0] if primitives else {}
    time_unit = str((first.get("config") or {}).get("time_unit") or "week")
    observable = (spec.get("observable_inputs") or [{}])[0]
    count_unit = str(observable.get("unit") or first.get("unit") or "items")
    for item in spec.get("observable_inputs") or []:
        metric = str(item.get("metric") or "")
        if not metric:
            continue
        requirements.append(
            StateRequirement(
                key=metric,
                label=metric.replace("_", " "),
                unit=str(item.get("unit") or "units"),
                why="This observable is bound to the compiled model.",
                aliases=tuple(item.get("aliases") or ()),
                required=bool(item.get("required", True)),
            )
        )
    for name in spec.get("required_parameters") or []:
        count_rate = name == "rate" and first.get("kind") == "cumulative_count"
        requirements.append(
            StateRequirement(
                key=name,
                label=f"{count_unit.capitalize()} per {time_unit}" if count_rate else name.replace("_", " "),
                unit=f"{count_unit}/{time_unit}" if count_rate else "parameter",
                why="Your expected pace, based on history or your own assumption." if count_rate else (
                    "The model needs this parameter from your history or an explicit assumption."
                ),
                required=True,
            )
        )
    return tuple(requirements)


def requirements_for(
    goal: GoalContract, proposal: GoalArchitectProposal | None = None
) -> tuple[str, tuple[StateRequirement, ...]] | None:
    """Return the model family label and the state vocabulary it consumes."""
    # Must stay in the same order as build_numeric_inputs, or the product would report
    # requirements for a family other than the one that prices the goal.
    spec = goal.model_requirements.get("forecast_spec") or {}
    if int(spec.get("spec_version") or 1) == 2 and spec.get("primitives"):
        family = str(spec.get("family") or "composed")
        return family, composition_requirements(spec)
    if is_hiring_goal(goal, proposal):
        return "hiring_funnel", hiring_requirements()
    if is_running_goal(goal, proposal):
        return "running_performance", running_requirements()
    if is_startup_goal(goal, proposal):
        return "startup_outcome", startup_requirements()
    if is_finance_goal(goal, proposal):
        return "wealth_accumulation", finance_requirements(goal)
    return None


def describe_priceability(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
) -> PriceabilityReport:
    match = requirements_for(goal, proposal)
    if match is None:
        return build_report(
            model_family="unmatched",
            requirements=(),
            resolution=resolve_state((), evidence),
            unsupported_reason=(
                "No numerical model family covers this goal yet, so we will not "
                "invent a probability for it."
            ),
        )
    family, requirements = match
    resolution = resolve_state(requirements, evidence, overrides=overrides)

    target = resolve_target(goal)
    if target is None:
        return build_report(
            model_family=family,
            requirements=requirements,
            resolution=resolution,
            unsupported_reason=(
                "This goal has no numeric success target, so there is nothing to simulate against."
            ),
        )
    if target.is_relative:
        return build_report(
            model_family=family,
            requirements=requirements,
            resolution=resolution,
            unsupported_reason=(
                f"The target is stated relative to another quantity ({target.raw!r}); "
                "we need an absolute number to price it."
            ),
        )
    return build_report(model_family=family, requirements=requirements, resolution=resolution)
