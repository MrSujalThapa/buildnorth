from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs, price_family
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.inputs_builder import proposal_from_goal as proposal_from_goal
from personal_markets.forecasting.priceability import describe_priceability
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.forecasting.requirements import PriceabilityReport
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal
from personal_markets.what_if.assumptions import (
    continuous_target_assumptions,
    hazard_assumptions,
)
from personal_markets.what_if.domain import (
    Assumption,
    CompareCandidate,
    InterventionChangeInput,
    MissingStateInput,
    PriceabilityView,
    ResourceBudget,
    ResourceCost,
    SatisfiedStateInput,
    SimulationConfig,
    StructuredIntervention,
    WhatIfBaselineState,
)
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import (
    apply_parsed_changes_to_assumptions,
    changes_to_state_overrides,
)

DEFAULT_SIM_CONFIG = SimulationConfig()
DEFAULT_EXECUTION = 0.72


@dataclass(frozen=True, slots=True)
class ResolvedSimulationContext:
    priced: bool
    message: str | None
    mode: Literal["continuous_target", "deadline_event", "unsupported"]
    current_value: float | None
    target_value: float | None
    periods: int | None
    direction: Literal["at_least", "at_most"]
    assumptions: list[Assumption]
    baseline_probability: float | None
    model_family: str
    model_version: str
    domain_state: dict[str, Any]
    reference_versions: tuple[str, ...]
    evidence_count: int
    evidence_watermark: str


def build_baseline_state(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    *,
    parsed_changes: list[InterventionChangeInput] | None = None,
    now: datetime | None = None,
) -> WhatIfBaselineState:
    registry = ForecastModelRegistry()
    proposal = proposal_from_goal(goal)
    overrides = _merged_overrides(parsed_changes)
    numeric = build_numeric_inputs(goal, proposal, evidence, overrides=overrides)
    model = registry.select_for(goal, numeric)
    resolved = _resolve_context(
        goal,
        model.descriptor.family,
        model.descriptor.version,
        numeric,
        evidence,
    )

    if not resolved.priced:
        report = describe_priceability(goal, proposal, evidence, overrides=overrides)
        view = _priceability_view(report)
        return WhatIfBaselineState(
            goal_id=str(goal.goal_id),
            priced=False,
            status=view.status,
            message=view.headline,
            priceability=view,
            model_family=model.descriptor.family,
            model_version=model.descriptor.version,
            evidence_count=len(evidence),
            evidence_watermark=_evidence_watermark(evidence),
            reference_versions=list(resolved.reference_versions),
            domain_state=resolved.domain_state,
            config=DEFAULT_SIM_CONFIG,
            compare_candidates=[],
        )

    assumptions = resolved.assumptions
    if parsed_changes:
        change_models = [
            InterventionChangeResponse.model_validate(item.model_dump()) for item in parsed_changes
        ]
        assumptions = apply_parsed_changes_to_assumptions(assumptions, change_models)

    intervention = _default_intervention(goal, resolved)
    constraints = _resource_constraints(goal)
    baseline = WhatIfBaselineState(
        goal_id=str(goal.goal_id),
        priced=True,
        status="EXPLORATORY",
        message=None,
        priceability=_priceability_view(
            describe_priceability(goal, proposal, evidence, overrides=overrides)
        ),
        current_value=resolved.current_value,
        target_value=resolved.target_value,
        periods=resolved.periods,
        direction=resolved.direction,
        current_probability=resolved.baseline_probability,
        assumptions=assumptions,
        default_intervention=intervention,
        model_family=resolved.model_family,
        model_version=resolved.model_version,
        evidence_count=len(evidence),
        evidence_watermark=_evidence_watermark(evidence),
        reference_versions=list(resolved.reference_versions),
        domain_state=resolved.domain_state,
        resource_constraints=constraints,
        resource_budget=_resource_budget(goal),
        limitations=_limitations(resolved),
        config=DEFAULT_SIM_CONFIG,
        compare_candidates=build_compare_candidates(goal, resolved, constraints),
    )
    return baseline


def _priceability_view(report: PriceabilityReport) -> PriceabilityView:
    return PriceabilityView(
        status=report.status,
        headline=report.headline,
        model_family=report.model_family,
        reason=report.reason,
        missing=[
            MissingStateInput(
                key=item.key,
                label=item.label,
                unit=item.unit,
                why=item.why,
                example=item.example,
                suggested_sources=list(item.suggested_sources),
            )
            for item in report.resolution.missing
        ],
        satisfied=[
            SatisfiedStateInput(
                key=item.key,
                label=next(
                    (req.label for req in report.requirements if req.key == item.key), item.key
                ),
                value=item.value,
                source=item.source,
                detail=item.detail,
            )
            for item in report.resolution.resolved.values()
        ],
    )


def resolve_simulation_context(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    *,
    parsed_changes: list[InterventionChangeInput] | None = None,
    assumption_overrides: dict[str, float] | None = None,
) -> ResolvedSimulationContext:
    registry = ForecastModelRegistry()
    proposal = proposal_from_goal(goal)
    # Resolve the unedited state first so relative edits are applied only once.
    numeric = build_numeric_inputs(goal, proposal, evidence)
    model = registry.select_for(goal, numeric)
    resolved = _resolve_context(
        goal, model.descriptor.family, model.descriptor.version, numeric, evidence
    )
    if not resolved.priced or not (assumption_overrides or parsed_changes):
        return resolved
    assumptions = resolved.assumptions
    if assumption_overrides:
        assumptions = _apply_user_assumption_overrides(assumptions, assumption_overrides)
    if parsed_changes:
        # State overrides only reach the domain builder's own vocabulary. Changes the
        # agent expressed against a model assumption (such as `flow`) have to be applied
        # here, after the user's slider values, or the action silently does nothing.
        change_models = [
            InterventionChangeResponse.model_validate(item.model_dump()) for item in parsed_changes
        ]
        assumptions = apply_parsed_changes_to_assumptions(assumptions, change_models)
    if resolved.mode == "deadline_event":
        overrides = {
            item.name.removeprefix("stage_rate_"): item.value
            for item in assumptions
            if item.name == "weekly_application_rate" or item.name.startswith("stage_rate_")
        }
        scenario_numeric = build_numeric_inputs(goal, proposal, evidence, overrides=overrides)
        scenario = _resolve_context(
            goal, model.descriptor.family, model.descriptor.version, scenario_numeric, evidence
        )
        return replace(scenario, assumptions=assumptions)
    return ResolvedSimulationContext(
        priced=resolved.priced,
        message=resolved.message,
        mode=resolved.mode,
        current_value=resolved.current_value,
        target_value=resolved.target_value,
        periods=resolved.periods,
        direction=resolved.direction,
        assumptions=assumptions,
        baseline_probability=resolved.baseline_probability,
        model_family=resolved.model_family,
        model_version=resolved.model_version,
        domain_state=resolved.domain_state,
        reference_versions=resolved.reference_versions,
        evidence_count=resolved.evidence_count,
        evidence_watermark=resolved.evidence_watermark,
    )


def _merged_overrides(
    parsed_changes: list[InterventionChangeInput] | None,
) -> dict[str, float | int] | None:
    if not parsed_changes:
        return None
    change_models = [
        InterventionChangeResponse.model_validate(item.model_dump()) for item in parsed_changes
    ]
    return changes_to_state_overrides(change_models)


def _resolve_context(
    goal: GoalContract,
    model_family: str,
    model_version: str,
    numeric: NumericInputs | None,
    evidence: list[NormalizedEvidence],
) -> ResolvedSimulationContext:
    empty = ResolvedSimulationContext(
        priced=False,
        message="No typed numerical state could be built from goal evidence.",
        mode="unsupported",
        current_value=None,
        target_value=None,
        periods=None,
        direction="at_least",
        assumptions=[],
        baseline_probability=None,
        model_family=model_family,
        model_version=model_version,
        domain_state={},
        reference_versions=(),
        evidence_count=len(evidence),
        evidence_watermark=_evidence_watermark(evidence),
    )
    if numeric is None:
        return empty

    from personal_markets.forecasting.composition import price_composition

    composed = price_composition(goal, numeric)
    if composed is not None:
        spec = goal.model_requirements.get("forecast_spec") or {}
        domain_state = _extract_domain_state(numeric)
        current = numeric.state.get("current_value")
        target = numeric.state.get("target_value")
        periods = numeric.state.get("periods")
        direction = str(numeric.state.get("direction") or "at_least")
        return ResolvedSimulationContext(
            priced=composed.priced,
            message=None if composed.priced else "; ".join(composed.limitations),
            mode="continuous_target" if composed.priced else "unsupported",
            current_value=None if current is None else float(current),
            target_value=None if target is None else float(target),
            periods=None if periods is None else int(periods),
            direction="at_most" if direction == "at_most" else "at_least",
            assumptions=[],
            baseline_probability=composed.raw_probability,
            model_family=str(spec.get("family") or "composed"),
            model_version=str(spec.get("model_version") or "composed_v1"),
            domain_state=domain_state,
            reference_versions=_reference_versions(numeric),
            evidence_count=len(evidence),
            evidence_watermark=_evidence_watermark(evidence),
        )

    registry = ForecastModelRegistry()
    model = registry.select_for(goal, numeric)
    priced = price_family(model, goal, numeric)
    domain_state = _extract_domain_state(numeric)
    reference_versions = _reference_versions(numeric)

    if model_family == "deadline_event_hazard":
        assumptions = hazard_assumptions(
            numeric, model_family=model_family, model_version=model_version
        )
        return ResolvedSimulationContext(
            priced=priced.priced,
            message=None if priced.priced else "; ".join(priced.limitations),
            mode="deadline_event",
            current_value=0.0,
            target_value=1.0,
            periods=int(numeric.state.get("periods_remaining") or 1),
            direction="at_least",
            assumptions=assumptions,
            baseline_probability=priced.raw_probability,
            model_family=model_family,
            model_version=model_version,
            domain_state=domain_state,
            reference_versions=reference_versions,
            evidence_count=len(evidence),
            evidence_watermark=_evidence_watermark(evidence),
        )

    if goal.goal_type not in {GoalType.CONTINUOUS_TARGET, GoalType.THRESHOLD}:
        return ResolvedSimulationContext(
            priced=False,
            message=f"{model_family} What If simulation is not yet supported for this goal type.",
            mode="unsupported",
            current_value=None,
            target_value=None,
            periods=None,
            direction="at_least",
            assumptions=[],
            baseline_probability=priced.raw_probability,
            model_family=model_family,
            model_version=model_version,
            domain_state=domain_state,
            reference_versions=reference_versions,
            evidence_count=len(evidence),
            evidence_watermark=_evidence_watermark(evidence),
        )

    current = numeric.state.get("current_value")
    target = numeric.state.get("target_value")
    periods = numeric.state.get("periods")
    direction = str(numeric.state.get("direction") or "at_least")
    if current is None or target is None or periods is None:
        return replace(
            empty,
            message="Missing current_value, target_value, or periods in domain state.",
            domain_state=domain_state,
            reference_versions=reference_versions,
        )

    assumptions = continuous_target_assumptions(
        goal, numeric, model_family=model_family, model_version=model_version
    )
    return ResolvedSimulationContext(
        priced=True,
        message=None,
        mode="continuous_target",
        current_value=float(current),
        target_value=float(target),
        periods=int(periods),
        direction="at_most" if direction == "at_most" else "at_least",
        assumptions=assumptions,
        baseline_probability=priced.raw_probability,
        model_family=model_family,
        model_version=model_version,
        domain_state=domain_state,
        reference_versions=reference_versions,
        evidence_count=len(evidence),
        evidence_watermark=_evidence_watermark(evidence),
    )


def _default_intervention(
    goal: GoalContract, resolved: ResolvedSimulationContext
) -> StructuredIntervention | None:
    if resolved.mode == "deadline_event":
        return StructuredIntervention(
            id="pipeline-plan",
            title="Increase application pipeline activity",
            action_type="pipeline_change",
            target_dimension="applications_per_week",
            amount=1,
            unit="applications/week",
            duration_periods=resolved.periods or 1,
            effect_per_unit=None,
            effect_source=None,
            diminishing_return=0.0,
            cost=_intervention_cost(goal),
        )
    metric = str(goal.success_definition.get("metric") or "target")
    is_threshold = goal.goal_type == GoalType.THRESHOLD
    return StructuredIntervention(
        id="primary-plan",
        title="Add focused training" if is_threshold else "Adjust recurring contribution",
        action_type="flow_change",
        target_dimension=metric,
        amount=1,
        unit="units/period",
        duration_periods=resolved.periods or 1,
        effect_per_unit=None,
        effect_source=None,
        diminishing_return=0.04,
        cost=_intervention_cost(goal),
    )


def _intervention_cost(goal: GoalContract) -> ResourceCost:
    constraints = goal.resource_constraints
    hours = float(constraints.hours_per_week or 0) if constraints else 0.0
    return ResourceCost(
        hours_per_week=min(1.5, hours) if hours else 1.0,
        money=0.0,
        energy=1.0,
    )


def build_compare_candidates(
    goal: GoalContract,
    resolved: ResolvedSimulationContext,
    constraints: ResourceCost,
) -> list[CompareCandidate]:
    hours = constraints.hours_per_week
    if hours <= 0:
        return []
    metric = str(
        goal.success_definition.get("metric") or goal.success_definition.get("event") or "target"
    )
    periods = resolved.periods or 1
    specs = (
        ("focused", "Focused allocation", min(2.0, hours)),
        ("balanced", "Balanced allocation", min(4.0, hours)),
        ("intensive", "Intensive allocation", min(7.0, hours)),
    )
    candidates: list[CompareCandidate] = []
    for index, (candidate_id, title, candidate_hours) in enumerate(specs):
        money = 200.0 if candidate_id == "intensive" else 0.0
        if money > constraints.money:
            money = 0.0
        candidates.append(
            CompareCandidate(
                id=candidate_id,
                title=title,
                intervention=StructuredIntervention(
                    id=candidate_id,
                    title=title,
                    action_type="resource_allocation",
                    target_dimension=metric,
                    amount=1,
                    unit="units/period",
                    duration_periods=periods,
                    effect_per_unit=None,
                    effect_source=None,
                    diminishing_return=0.08,
                    cost=ResourceCost(
                        hours_per_week=candidate_hours,
                        money=money,
                        energy=candidate_hours / 2,
                    ),
                ),
                provenance=[
                    "REFERENCE:goal.resource_constraints",
                    f"EXPLORATION_ASSUMPTION:allocation_tier_{index + 1}",
                ],
            )
        )
    return candidates


def _resource_budget(goal: GoalContract) -> ResourceBudget:
    constraints = goal.resource_constraints
    if constraints is None:
        return ResourceBudget()
    return ResourceBudget(
        hours_per_week=float(constraints.hours_per_week or 0),
        money_per_month=float(constraints.budget_amount or 0),
    )


def _limitations(resolved: ResolvedSimulationContext) -> list[str]:
    notes: list[str] = []
    if resolved.mode == "deadline_event":
        notes.append(
            "Observed funnel counts are immutable evidence; only future pipeline "
            "assumptions are editable."
        )
    if not resolved.reference_versions:
        notes.append("No reference dataset version attached to this baseline.")
    return notes


def _resource_constraints(goal: GoalContract) -> ResourceCost:
    constraints = goal.resource_constraints
    if constraints is None:
        return ResourceCost()
    return ResourceCost(
        hours_per_week=float(constraints.hours_per_week or 0),
        money=float(constraints.budget_amount or 0),
        energy=float(constraints.hours_per_week or 0),
    )


def _extract_domain_state(numeric: NumericInputs) -> dict[str, Any]:
    transforms = numeric.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        payload = {key: value for key, value in transforms.items() if key != "reference_version"}
        payload["assumptions"] = numeric.assumptions
        return payload
    return {"assumptions": numeric.assumptions}


def _reference_versions(numeric: NumericInputs) -> tuple[str, ...]:
    transforms = numeric.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        version = transforms.get("reference_version")
        if isinstance(version, str):
            return (version,)
    return ()


def _evidence_watermark(evidence: list[NormalizedEvidence]) -> str:
    if not evidence:
        return "none"
    stamps = [item.observed_at for item in evidence if item.observed_at is not None]
    return max(stamps).isoformat() if stamps else "none"


def _map_source(source: str) -> AssumptionSource:
    mapping = {
        "REAL_USER_EVIDENCE": AssumptionSource.USER,
        "REFERENCE": AssumptionSource.REFERENCE,
        "FITTED": AssumptionSource.FITTED,
        "USER_ASSUMPTION": AssumptionSource.USER,
        "EXPLORATION_ASSUMPTION": AssumptionSource.EXPLORATION,
    }
    return mapping.get(source, AssumptionSource.REFERENCE)


def _apply_user_assumption_overrides(
    assumptions: list[Assumption], overrides: dict[str, float]
) -> list[Assumption]:
    updated: list[Assumption] = []
    for item in assumptions:
        if item.name in overrides:
            value = overrides[item.name]
            updated.append(
                item.model_copy(
                    update={
                        "value": max(item.minimum, min(item.maximum, value)),
                        "source": AssumptionSource.USER,
                    }
                )
            )
        else:
            updated.append(item)
    return updated
