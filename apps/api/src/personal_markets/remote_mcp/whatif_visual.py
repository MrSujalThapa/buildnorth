"""Owner-scoped What If transport. Numerical results come only from WhatIfService."""

from __future__ import annotations

from typing import Any, Literal

from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.domain import (
    ContinuousSearchVariable,
    InterventionChangeInput,
    PathComparisonRequest,
    PathDefinition,
    PossibleFuturesRequest,
    ResourceLimitsInput,
    ScenarioDefinition,
    SimulationConfig,
    StructuredIntervention,
    TargetSearchRequest,
    WhatIfBaselineState,
)
from personal_markets.what_if.futures_decision import parse_futures_decision
from personal_markets.what_if.intervention_parser import parse_intervention_text

Mode = Literal["impact", "futures", "compare", "paths"]
Depth = Literal["simple", "deep"]


def config_for_depth(seed: int, depth: Depth) -> SimulationConfig:
    """Match the existing website's simulationConfigForView."""
    if depth == "deep":
        return SimulationConfig(
            seed=seed,
            minimum_draws=8000,
            batch_draws=4000,
            maximum_draws=20000,
            include_sensitivity=True,
        )
    return SimulationConfig(
        seed=seed,
        minimum_draws=2000,
        batch_draws=2000,
        maximum_draws=4000,
        include_sensitivity=False,
    )


def request_from_baseline(goal_id: str, baseline: WhatIfBaselineState, depth: Depth) -> Any:
    from personal_markets.what_if.domain import WhatIfRequest

    return WhatIfRequest(
        goal_id=goal_id,
        current_value=baseline.current_value if baseline.current_value is not None else 0,
        target_value=baseline.target_value if baseline.target_value is not None else 1,
        periods=baseline.periods or 8,
        direction=baseline.direction,
        assumptions=baseline.assumptions,
        intervention=None,
        config=config_for_depth(baseline.config.seed, depth),
    )


async def build_visual_payload(
    *,
    goal: GoalContract,
    service: Any,
    mode: Mode,
    view: Depth,
    question: str,
    target_probability: float | None,
    request_id: str | None,
    alternatives: list[str] | None = None,
) -> dict[str, Any]:
    """Run the same engine operations used by the website; never persist simulations."""
    goal_id = str(goal.goal_id)
    baseline = await service.baseline_state(goal_id)
    history = await service.history(goal_id)
    payload: dict[str, Any] = {
        "kind": "playitout_what_if",
        "request_id": request_id,
        "goal": goal.model_dump(mode="json"),
        "history": [row.model_dump(mode="json") for row in history],
        "baseline": baseline.model_dump(mode="json"),
        "mode": mode,
        "view": view,
        "question": question,
        "targetProbability": target_probability,
        "state": "ready" if baseline.priced else "unpriced",
        "message": baseline.message if not baseline.priced else None,
    }
    if not baseline.priced:
        return payload

    base = request_from_baseline(goal_id, baseline, view)
    if mode == "impact":
        parsed = parse_intervention_text(question)
        if not parsed.changes:
            payload.update(
                state="unpriced",
                message=(
                    "This question has no supported quantitative change. "
                    "Specify an observable amount and period."
                ),
            )
            return payload
        request = base.model_copy(
            update={
                "parsed_changes": [
                    InterventionChangeInput(
                        metric=item.metric,
                        operation=item.operation,
                        value=item.value,
                        unit=item.unit,
                        frequency=item.frequency,
                        scope=item.scope,
                        provenance=item.provenance,
                    )
                    for item in parsed.changes
                ]
            }
        )
        result = await service.fast_reprice(request)
        payload["scenario"] = result.model_dump(mode="json")
        if not result.priced:
            payload.update(state="unpriced", message=result.message)
    elif mode == "futures":
        decision = parse_futures_decision(question, goal=goal)
        if not decision.scenario_labels:
            payload.update(
                state="unpriced", message="No modeled outcome families match this question."
            )
            return payload
        result = await service.possible_futures(
            PossibleFuturesRequest(
                goal_id=goal_id,
                name=question,
                outcomes=[
                    ScenarioDefinition(
                        label=label,
                        downside=any(
                            word in label.lower()
                            for word in ("downside", "fail", "delay", "no offer", "return to job")
                        ),
                    )
                    for label in decision.scenario_labels
                ],
                assumptions=baseline.assumptions,
                evidence_basis=[f"decision:{question[:120]}"],
                seed=base.config.seed,
                config=base.config,
            )
        )
        payload["futures"] = result.model_dump(mode="json")
        if not result.priced:
            payload.update(state="unpriced", message=result.message)
    elif mode == "compare":
        candidates = baseline.compare_candidates
        if alternatives and len(alternatives) >= 2:
            paths = []
            for index, label in enumerate(alternatives[:5]):
                parsed = parse_intervention_text(label)
                prototype = baseline.default_intervention
                intervention = (
                    prototype.model_copy(
                        update={
                            "id": f"custom-{index}",
                            "title": label,
                            "effect_per_unit": None,
                            "effect_source": None,
                        }
                    )
                    if prototype
                    else StructuredIntervention(
                        id=f"custom-{index}",
                        title=label,
                        action_type="flow_change",
                        target_dimension="target",
                        amount=1,
                        unit="units/period",
                        duration_periods=baseline.periods or 8,
                    )
                )
                paths.append(
                    PathDefinition(
                        id=f"custom-{index}",
                        label=label,
                        intervention=intervention,
                        parsed_changes=[
                            InterventionChangeInput(
                                metric=item.metric,
                                operation=item.operation,
                                value=item.value,
                                unit=item.unit,
                                frequency=item.frequency,
                                scope=item.scope,
                                provenance=item.provenance,
                            )
                            for item in parsed.changes
                        ],
                    )
                )
        elif "compare these" in question.lower():
            payload.update(state="unpriced", message="Name at least two alternatives to compare.")
            return payload
        else:
            paths = [
                PathDefinition(
                    id=item.id,
                    label=item.title,
                    intervention=item.intervention,
                )
                for item in candidates[:5]
            ]
        if len(paths) < 2:
            payload.update(
                state="unpriced", message="Two supported model paths are required for comparison."
            )
            return payload
        result = await service.compare_paths(PathComparisonRequest(base=base, paths=paths))
        payload["comparison"] = result.model_dump(mode="json")
        if not any(item.primary_goal_probability is not None for item in result.paths):
            payload.update(
                state="unpriced", message="These paths have no modeled probability effect."
            )
    else:
        target = target_probability if target_probability is not None else 0.85
        if not 0 < target < 1:
            payload.update(state="failed", message="Target probability must be between 0 and 1.")
            return payload
        names = {item.name for item in baseline.assumptions}
        continuous = (
            ContinuousSearchVariable(assumption="flow", increasing=True)
            if "flow" in names
            else ContinuousSearchVariable(assumption="weekly_application_rate", increasing=True)
            if "weekly_application_rate" in names
            else None
        )
        result = await service.target_search(
            TargetSearchRequest(
                base=base,
                target_probability=target,
                candidates=[item.intervention for item in baseline.compare_candidates],
                limits=ResourceLimitsInput(
                    hours_per_week=baseline.resource_constraints.hours_per_week or 20,
                    money=baseline.resource_budget.money_per_month,
                    energy=1,
                ),
                continuous_variable=continuous,
            )
        )
        payload["targetSearch"] = result.model_dump(mode="json")
        payload["targetProbability"] = target
        if not result.feasible:
            payload["message"] = result.message
    return payload
