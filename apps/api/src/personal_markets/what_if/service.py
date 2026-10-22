from __future__ import annotations

import hashlib
import json
from uuid import UUID

import numpy as np

from personal_markets.behavior.commitments import get_commitment_store, trials_from_commitments
from personal_markets.behavior.features import context_from_text
from personal_markets.behavior.service import BehaviorService
from personal_markets.demo_fixtures import (
    demo_fixtures_enabled,
    fixture_action_frontier,
    fixture_compare,
    fixture_futures,
    fixture_simulate,
    fixture_target_search,
    is_demo_goal,
    patch_baseline_state,
)
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.forecasting.primitives import at_numerical_bound
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.what_if.baseline_state import (
    build_baseline_state,
    resolve_simulation_context,
)
from personal_markets.what_if.domain import (
    ActionFrontierResult,
    DistributionBin,
    FrontierPoint,
    MarketHistoryPointResponse,
    PathComparisonItem,
    PathComparisonRequest,
    PathComparisonResult,
    PossibleFuturesRequest,
    ResourceCost,
    ScenarioDistribution,
    ScenarioOutcome,
    StructuredIntervention,
    TargetPath,
    TargetSearchRequest,
    TargetSearchResult,
    WhatIfBaselineState,
    WhatIfExplorationResponse,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.futures_weights import resolve_futures_weights
from personal_markets.what_if.intervals import sampling_uplift_interval_pp
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import (
    apply_parsed_changes_to_assumptions,
    unmapped_change_metrics,
)
from personal_markets.what_if.optimizer import ActionOptimizer, ResourceLimits
from personal_markets.what_if.repository import (
    InMemorySimulationRepository,
    MarketHistoryPoint,
    SimulationRepository,
)
from personal_markets.what_if.resources import (
    budget_from_goal,
    evaluate_resource_usage,
    execution_scale_for_budget,
    opportunity_cost_messages,
)
from personal_markets.what_if.sensitivity import compute_sensitivity, outcome_distribution_bins
from personal_markets.what_if.simulation import PairedSimulation, SimulationEngine


class WhatIfService:
    def __init__(
        self,
        goals: GoalService,
        repository: SimulationRepository | None = None,
        engine: SimulationEngine | None = None,
        evidence: EvidenceService | None = None,
        behavior: BehaviorService | None = None,
        owner_id: UUID | None = None,
    ) -> None:
        self._goals = goals
        self._engine = engine or SimulationEngine()
        self._registry = ForecastModelRegistry()
        self._repository = repository or InMemorySimulationRepository()
        self._evidence = evidence
        self._behavior = behavior or BehaviorService()
        self._owner_id = owner_id

    async def _require_goal(self, goal_id: str) -> GoalContract:
        return await self._goals.get_goal_by_string(goal_id, owner_id=self._owner_id)

    async def baseline_state(self, goal_id: str) -> WhatIfBaselineState:
        goal = await self._require_goal(goal_id)
        evidence: list = []
        if self._evidence is not None:
            evidence = await self._evidence.list_for_goal(UUID(goal_id))
        state = build_baseline_state(goal, evidence)
        if demo_fixtures_enabled() and is_demo_goal(goal_id):
            return patch_baseline_state(state)
        return await self._overlay_published_baseline(UUID(goal_id), state)

    async def _overlay_published_baseline(
        self, goal_id: UUID, state: WhatIfBaselineState
    ) -> WhatIfBaselineState:
        history = await self._repository.history(goal_id)
        published = [point for point in history if point.source_kind == "published_forecast"]
        if published:
            latest = published[-1]
            return state.model_copy(
                update={
                    "priced": True,
                    "status": latest.forecast_status,
                    "current_probability": latest.probability,
                }
            )
        return state

    async def simulate(self, request: WhatIfRequest) -> WhatIfResult:
        if demo_fixtures_enabled() and is_demo_goal(request.goal_id):
            fixture = fixture_simulate(request.goal_id)
            if fixture is not None:
                return fixture
        return await self._simulate(request, persist=True)

    async def fast_reprice(self, request: WhatIfRequest) -> WhatIfResult:
        if demo_fixtures_enabled() and is_demo_goal(request.goal_id):
            fixture = fixture_simulate(request.goal_id)
            if fixture is not None:
                return fixture
        return await self._simulate(request, persist=False)

    async def _simulate_composition(
        self, goal: GoalContract, request: WhatIfRequest, evidence: list, *, persist: bool
    ) -> WhatIfResult | None:
        from personal_markets.forecasting.compiler import spec_from_mapping
        from personal_markets.forecasting.composition import (
            composition_numeric_inputs,
            price_composition,
        )
        from personal_markets.forecasting.engine import NumericInputs
        from personal_markets.forecasting.inputs_builder import (
            build_numeric_inputs,
            proposal_from_goal,
        )

        spec = spec_from_mapping(goal.model_requirements.get("forecast_spec"))
        if spec is None:
            return None
        proposal = proposal_from_goal(goal)
        baseline_inputs = build_numeric_inputs(goal, proposal, evidence)
        if baseline_inputs is None:
            baseline_inputs = composition_numeric_inputs(goal, evidence)
        baseline = price_composition(goal, baseline_inputs or NumericInputs())
        if baseline is None:
            return None
        overrides: dict[str, float] = {}
        unmapped: list[str] = []
        baseline_assumptions = baseline_inputs.assumptions if baseline_inputs else {}
        assumption_names = set(baseline_assumptions.keys())
        for change in request.parsed_changes or []:
            metric = change.metric
            short = metric.split(".", 1)[-1]
            if (
                metric in assumption_names
                or any(name.endswith(f".{short}") for name in assumption_names)
                or short
                in {
                    "rate",
                    "mu",
                    "sigma",
                    "trend",
                    "noise",
                    "inflow_rate",
                }
            ):
                key = metric if metric in assumption_names else short
                if change.operation == "set":
                    overrides[key] = change.value
                else:
                    qualified = [name for name in assumption_names if name.endswith(f".{short}")]
                    source = key if key in assumption_names else None
                    if source is None and len(qualified) == 1:
                        source = qualified[0]
                    if source is None:
                        unmapped.append(metric)
                        continue
                    current = float(baseline_assumptions.get(source) or 0.0)
                    overrides[key] = (
                        current + change.value
                        if change.operation == "add"
                        else current - change.value
                    )
            else:
                unmapped.append(metric)
        if not overrides:
            detail = f"Unmapped: {', '.join(unmapped)}. " if unmapped else ""
            result = WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=(
                    "This action is not mapped to a supported model parameter. "
                    f"{detail}Describe a change in the measured rate, or add evidence "
                    "linking this action to that rate. Hypothetical causal effects "
                    "were not invented."
                ),
                baseline_probability=baseline.raw_probability,
                assumptions=request.assumptions,
                receipt={
                    "causal_status": "unmapped_intervention",
                    "unmapped": unmapped,
                    "hypothetical": True,
                },
            )
            if persist:
                return await self._persist(request, result, spec.family, spec.compiler_version)
            return result
        scenario_inputs = (
            composition_numeric_inputs(goal, evidence, overrides=overrides) or baseline_inputs
        )
        scenario = price_composition(goal, scenario_inputs or baseline_inputs)
        if (
            not baseline.priced
            or baseline.raw_probability is None
            or scenario is None
            or not scenario.priced
        ):
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message="; ".join(baseline.limitations or ["Composition is not priceable yet."]),
                baseline_probability=baseline.raw_probability,
                assumptions=request.assumptions,
            )
        uplift = (scenario.raw_probability - baseline.raw_probability) * 100.0
        limitations = list(scenario.limitations)
        bound = at_numerical_bound(baseline.raw_probability) or at_numerical_bound(
            scenario.raw_probability
        )
        if bound:
            limitations.append(
                "One or both probabilities sit on the primitive numerical bound. "
                "The percentage-point difference is a hypothetical model-parameter "
                "change, not a calibrated causal effect of the described action."
            )
        message = (
            limitations[-1]
            if bound
            else (
                "This What If changes a fitted model parameter. It is a hypothetical "
                "scenario, not an actionable intervention with identified causal support."
            )
        )
        result = WhatIfResult(
            priced=True,
            status="EXPLORATORY",
            message=message,
            baseline_probability=baseline.raw_probability,
            scenario_probability=scenario.raw_probability,
            expected_uplift_pp=uplift,
            uplift_interval_pp=None,
            assumptions=request.assumptions,
            receipt={
                "hypothetical": True,
                "causal_status": "parameter_intervention",
                "compiler_version": spec.compiler_version,
                "overrides": overrides,
                "limitations": limitations,
                "numerical_bound": bound,
            },
        )
        if persist:
            return await self._persist(request, result, spec.family, spec.compiler_version)
        return result

    @staticmethod
    def _unmapped_changes_result(request: WhatIfRequest, assumptions: list) -> WhatIfResult | None:
        if not request.parsed_changes:
            return None
        if request.intervention is not None and request.intervention.effect_per_unit is not None:
            return None
        metrics = [item.metric for item in request.parsed_changes]
        unmapped = unmapped_change_metrics({item.name for item in assumptions}, metrics)
        if len(unmapped) < len(metrics):
            return None
        return WhatIfResult(
            priced=False,
            status="NOT_PRICED",
            message=(
                "This action is not mapped to a supported model parameter. "
                f"Unmapped: {', '.join(unmapped)}. Hypothetical causal effects were not invented."
            ),
            assumptions=request.assumptions,
            receipt={
                "causal_status": "unmapped_intervention",
                "unmapped": unmapped,
                "hypothetical": True,
            },
        )

    async def _simulate(self, request: WhatIfRequest, *, persist: bool) -> WhatIfResult:
        goal = await self._require_goal(request.goal_id)
        model = self._registry.select(goal)

        if self._evidence is not None:
            evidence = await self._evidence.list_for_goal(UUID(request.goal_id))
            composed = await self._simulate_composition(goal, request, evidence, persist=persist)
            if composed is not None:
                return composed
            explicit_trials = []
            if self._owner_id is not None:
                plans, observations = await get_commitment_store().list_for_goals(
                    self._owner_id, [goal.goal_id]
                )
                explicit_trials = trials_from_commitments(plans, observations)
            request = self._apply_behavior_execution(
                goal, request, evidence, commitment_trials=explicit_trials
            )
            user_overrides = {item.name: item.value for item in request.assumptions}
            baseline_ctx = resolve_simulation_context(
                goal, evidence, parsed_changes=[], assumption_overrides=user_overrides
            )
            scenario_ctx = resolve_simulation_context(
                goal,
                evidence,
                parsed_changes=request.parsed_changes,
                assumption_overrides=user_overrides,
            )
            if baseline_ctx.priced:
                unpriced = self._unmapped_changes_result(request, baseline_ctx.assumptions)
                if unpriced is not None:
                    return unpriced
                # Report the family that actually priced the state, not the one implied
                # by goal type alone.
                resolved_model = self._registry.family_named(baseline_ctx.model_family, goal)
                if baseline_ctx.mode == "deadline_event":
                    # Both arms share the assumption overrides, so a persisted scenario
                    # without a mapped change would record a fabricated zero effect.
                    if persist and not request.parsed_changes:
                        return WhatIfResult(
                            priced=False,
                            status="NOT_PRICED",
                            message=(
                                "This action did not map to a supported model parameter. "
                                "Hypothetical causal effects were not invented."
                            ),
                            baseline_probability=baseline_ctx.baseline_probability,
                            assumptions=request.assumptions,
                            receipt={
                                "causal_status": "unmapped_intervention",
                                "unmapped": [],
                                "hypothetical": True,
                            },
                        )
                    return await self._simulate_deadline_event(
                        goal, request, baseline_ctx, scenario_ctx, resolved_model, persist
                    )
                if baseline_ctx.mode == "continuous_target":
                    return await self._simulate_continuous_domain(
                        goal, request, baseline_ctx, scenario_ctx, resolved_model, persist
                    )

        if goal.goal_type not in {GoalType.CONTINUOUS_TARGET, GoalType.THRESHOLD}:
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=(
                    f"{model.descriptor.family} requires evidence-backed numerical state "
                    "before What If can price scenarios."
                ),
                assumptions=request.assumptions,
            )
        return await self._simulate_continuous_request(goal, request, model, persist)

    async def _simulate_continuous_domain(
        self,
        goal: GoalContract,
        request: WhatIfRequest,
        baseline_ctx: object,
        scenario_ctx: object,
        model: object,
        persist: bool,
    ) -> WhatIfResult:
        from personal_markets.what_if.baseline_state import ResolvedSimulationContext

        assert isinstance(baseline_ctx, ResolvedSimulationContext)
        assert isinstance(scenario_ctx, ResolvedSimulationContext)
        baseline_values = {item.name: item.value for item in baseline_ctx.assumptions}
        scenario_values = {item.name: item.value for item in scenario_ctx.assumptions}
        required = {
            "flow",
            "growth_mean",
            "growth_volatility",
            "shock_probability",
            "shock_fraction",
            "execution_probability",
        }
        missing = sorted(required - baseline_values.keys())
        if missing:
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=f"Missing assumptions: {', '.join(missing)}.",
                assumptions=scenario_ctx.assumptions,
            )

        intervention = request.intervention
        raw_effect = 0.0
        if intervention is not None and intervention.effect_per_unit is not None:
            raw_effect = intervention.amount * intervention.effect_per_unit
            raw_effect = raw_effect / (
                1 + intervention.diminishing_return * abs(intervention.amount)
            )
        elif (
            intervention is not None
            and intervention.effect_per_unit is None
            and not request.parsed_changes
        ):
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=(
                    "Supply parsed intervention changes or an explicit "
                    "exploration effect assumption."
                ),
                assumptions=scenario_ctx.assumptions,
                opportunity_costs=self._opportunity_costs(intervention),
            )

        assert baseline_ctx.current_value is not None
        assert baseline_ctx.target_value is not None
        assert baseline_ctx.periods is not None

        # One paired run: both arms share the same draws, and the scenario state only
        # applies on paths where the user executes.
        paired = self._engine.continuous_target(
            current_value=baseline_ctx.current_value,
            target_value=baseline_ctx.target_value,
            periods=baseline_ctx.periods,
            direction=baseline_ctx.direction,
            flow=baseline_values["flow"],
            growth_mean=baseline_values["growth_mean"],
            growth_volatility=baseline_values["growth_volatility"],
            shock_probability=baseline_values["shock_probability"],
            shock_fraction=baseline_values["shock_fraction"],
            execution_probability=scenario_values["execution_probability"],
            intervention_effect=raw_effect,
            config=request.config,
            scenario_flow=scenario_values["flow"],
            scenario_growth_mean=scenario_values["growth_mean"],
            scenario_growth_volatility=scenario_values["growth_volatility"],
            scenario_shock_probability=scenario_values["shock_probability"],
            scenario_shock_fraction=scenario_values["shock_fraction"],
        )
        scenario_paired = paired
        return await self._build_result_from_paired(
            goal=goal,
            request=request,
            paired=paired,
            scenario_paired=scenario_paired,
            assumptions=scenario_ctx.assumptions,
            intervention=intervention,
            model_family=model.descriptor.family,
            model_version=model.descriptor.version,
            persist=persist,
            baseline_probability=baseline_ctx.baseline_probability,
            mode=baseline_ctx.mode,
            intervention_effect=raw_effect,
        )

    async def _simulate_deadline_event(
        self,
        goal: GoalContract,
        request: WhatIfRequest,
        baseline_ctx: object,
        scenario_ctx: object,
        model: object,
        persist: bool,
    ) -> WhatIfResult:
        from personal_markets.what_if.baseline_state import ResolvedSimulationContext

        assert isinstance(baseline_ctx, ResolvedSimulationContext)
        assert isinstance(scenario_ctx, ResolvedSimulationContext)
        baseline_prob = baseline_ctx.baseline_probability or 0.0
        scenario_prob = (
            scenario_ctx.baseline_probability
            if scenario_ctx.baseline_probability is not None
            else baseline_prob
        )
        execution = next(
            (
                item.value
                for item in scenario_ctx.assumptions
                if item.name == "execution_probability"
            ),
            0.72,
        )
        periods = baseline_ctx.periods or 1
        paired = self._engine.deadline_event(
            baseline_probability=baseline_prob,
            scenario_probability=scenario_prob,
            periods=periods,
            execution_probability=execution,
            config=request.config,
        )
        intervention = request.intervention
        return await self._build_result_from_paired(
            goal=goal,
            request=request,
            paired=paired,
            scenario_paired=paired,
            assumptions=scenario_ctx.assumptions,
            intervention=intervention,
            model_family=model.descriptor.family,
            model_version=model.descriptor.version,
            persist=persist,
            baseline_probability=baseline_prob,
            mode=baseline_ctx.mode,
            scenario_override=scenario_prob,
            intervention_effect=0.0,
        )

    async def _simulate_continuous_request(
        self,
        goal: GoalContract,
        request: WhatIfRequest,
        model: object,
        persist: bool,
    ) -> WhatIfResult:
        effective_assumptions = request.assumptions
        if request.parsed_changes:
            change_models = [
                InterventionChangeResponse.model_validate(item.model_dump())
                for item in request.parsed_changes
            ]
            effective_assumptions = apply_parsed_changes_to_assumptions(
                request.assumptions, change_models
            )
        values = {item.name: item.value for item in effective_assumptions}
        required = {
            "flow",
            "growth_mean",
            "growth_volatility",
            "shock_probability",
            "shock_fraction",
            "execution_probability",
        }
        missing = sorted(required - values.keys())
        if missing:
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=(
                    "Scenario cannot yet be numerically priced. Missing assumptions: "
                    f"{', '.join(missing)}."
                ),
                assumptions=effective_assumptions,
            )
        intervention = request.intervention
        if intervention is not None and intervention.effect_per_unit is None:
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                message=(
                    "Scenario cannot yet be numerically priced. Supply an explicit effect "
                    "assumption or reference-derived effect model."
                ),
                assumptions=effective_assumptions,
                opportunity_costs=self._opportunity_costs(intervention),
            )
        raw_effect = 0.0
        if intervention is not None:
            assert intervention.effect_per_unit is not None
            raw_effect = intervention.amount * intervention.effect_per_unit
            raw_effect = raw_effect / (
                1 + intervention.diminishing_return * abs(intervention.amount)
            )
        paired = self._engine.continuous_target(
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
            intervention_effect=raw_effect,
            config=request.config,
        )
        return await self._build_result_from_paired(
            goal=goal,
            request=request,
            paired=paired,
            scenario_paired=paired,
            assumptions=effective_assumptions,
            intervention=intervention,
            model_family=model.descriptor.family,
            model_version=model.descriptor.version,
            persist=persist,
            mode="continuous_target",
            intervention_effect=raw_effect,
        )

    async def _build_result_from_paired(
        self,
        *,
        goal: GoalContract,
        request: WhatIfRequest,
        paired: object,
        scenario_paired: object,
        assumptions: list,
        intervention: StructuredIntervention | None,
        model_family: str,
        model_version: str,
        persist: bool,
        mode: str = "continuous_target",
        baseline_probability: float | None = None,
        scenario_override: float | None = None,
        intervention_effect: float = 0.0,
    ) -> WhatIfResult:
        assert isinstance(paired, PairedSimulation)
        assert isinstance(scenario_paired, PairedSimulation)
        baseline = (
            baseline_probability
            if baseline_probability is not None
            else float(np.mean(paired.baseline_success))
        )
        scenario = (
            scenario_override
            if scenario_override is not None
            else float(np.mean(scenario_paired.scenario_success))
        )
        executed = scenario_paired.execution
        conditional = (
            float(np.mean(scenario_paired.scenario_success[executed]))
            if np.any(executed)
            else baseline
        )
        values = {item.name: item.value for item in assumptions}
        execution_probability = values.get("execution_probability", 0.72)
        if mode == "deadline_event" and scenario_override is not None:
            conditional = scenario_override
            scenario = baseline + execution_probability * (conditional - baseline)
        budget = budget_from_goal(goal)
        usage = evaluate_resource_usage(intervention, budget)
        scaled_execution, scale_notes = execution_scale_for_budget(
            execution_probability, usage, budget
        )
        if not usage.within_budget and execution_probability > 0:
            scenario = baseline + (scenario - baseline) * (scaled_execution / execution_probability)
            conditional = baseline + (conditional - baseline) * (
                scaled_execution / execution_probability
            )
            execution_probability = scaled_execution

        delta = scenario_paired.scenario_success.astype(float) - paired.baseline_success.astype(
            float
        )
        chunk_deltas = np.asarray(
            [float(np.mean(chunk)) for chunk in np.array_split(delta, min(20, len(delta)))]
        )
        outcome_delta = scenario_paired.scenario_outcome - paired.baseline_outcome
        quantile_values = np.quantile(scenario_paired.scenario_outcome, [0.1, 0.25, 0.5, 0.75, 0.9])
        fan = self._fan(scenario_paired.scenario_trajectory)
        bin_payload = outcome_distribution_bins(scenario_paired.scenario_outcome)
        distribution_bins = [DistributionBin.model_validate(item) for item in bin_payload]

        evidence: list = []
        if self._evidence is not None:
            evidence = await self._evidence.list_for_goal(UUID(request.goal_id))
        sensitivity = compute_sensitivity(
            goal=goal,
            evidence=evidence,
            request=request,
            assumptions=assumptions,
            baseline_probability=baseline,
            intervention_effect=intervention_effect,
            mode=mode,
            engine=self._engine,
        )
        opportunity_costs = (
            []
            if intervention is None
            else opportunity_cost_messages(intervention, usage) + scale_notes
        )
        profile = getattr(self, "_last_behavior_profile", None)
        interval = None
        if profile is not None:
            interval = list(profile.execution.interval)
        result = WhatIfResult(
            priced=True,
            status="EXPLORATORY" if usage.within_budget else "EXPLORATORY_OVER_BUDGET",
            baseline_probability=baseline,
            scenario_probability=scenario,
            conditional_on_execution_probability=conditional,
            execution_probability=execution_probability,
            expected_uplift_pp=(scenario - baseline) * 100,
            uplift_interval_pp=sampling_uplift_interval_pp(chunk_deltas),
            p_uplift_positive=float(np.mean(outcome_delta > 0)),
            outcome_quantiles=dict(
                zip(("p10", "p25", "p50", "p75", "p90"), map(float, quantile_values), strict=True)
            ),
            expected_outcome=float(np.mean(scenario_paired.scenario_outcome)),
            downside_probability=float(
                np.mean(scenario_paired.scenario_outcome < paired.baseline_outcome)
                if request.direction == "at_least"
                else np.mean(scenario_paired.scenario_outcome > paired.baseline_outcome)
            ),
            fan=fan,
            distribution_bins=distribution_bins,
            assumptions=assumptions,
            opportunity_costs=opportunity_costs,
            resource_usage=usage,
            resource_budget=budget,
            resource_feasible=usage.within_budget,
            diagnostics=scenario_paired.diagnostics,
            sensitivity=sensitivity,
            fragility_pp=float(np.mean([item.swing / 2 for item in sensitivity[:3]]))
            if sensitivity
            else 0,
            execution_breakdown={
                "current_probability": baseline,
                "conditional_on_full_execution": conditional,
                "follow_through_probability": execution_probability,
                "execution_adjusted_probability": scenario,
                "interval": interval,
                "source": (
                    profile.execution.source
                    if profile is not None
                    else next(
                        (
                            item.source
                            for item in assumptions
                            if item.name == "execution_probability"
                        ),
                        "USER_ASSUMPTION",
                    )
                ),
            },
            behavior_profile=profile.model_dump(mode="json") if profile is not None else None,
        )
        if persist:
            return await self._persist(request, result, model_family, model_version)
        return result

    def _history_response(self, point: MarketHistoryPoint) -> MarketHistoryPointResponse:
        return MarketHistoryPointResponse(
            id=str(point.id),
            probability=point.probability,
            forecast_status=point.forecast_status,
            evidence_watermark=point.evidence_watermark,
            model_family=point.model_family,
            model_version=point.model_version,
            assumption_hash=point.assumption_hash,
            simulation_run_id=(
                str(point.simulation_artifact_id) if point.simulation_artifact_id else None
            ),
            source_kind=point.source_kind,
            created_at=point.created_at.isoformat() if point.created_at else None,
        )

    async def history(self, goal_id: str) -> list[MarketHistoryPointResponse]:
        await self._require_goal(goal_id)
        points = await self._repository.history(UUID(goal_id))
        return [self._history_response(point) for point in points]

    async def histories(self, goal_ids: list[str]) -> dict[str, list[MarketHistoryPointResponse]]:
        unique: list[UUID] = []
        seen: set[UUID] = set()
        for raw in goal_ids:
            goal_id = UUID(raw)
            if goal_id in seen:
                continue
            seen.add(goal_id)
            await self._require_goal(str(goal_id))
            unique.append(goal_id)
        return await self.histories_for_owned(unique)

    async def histories_for_owned(
        self, goal_ids: list[UUID]
    ) -> dict[str, list[MarketHistoryPointResponse]]:
        grouped = await self._repository.history_for_goals(goal_ids)
        return {
            str(goal_id): [self._history_response(point) for point in grouped.get(goal_id, [])]
            for goal_id in goal_ids
        }

    async def explorations(self, goal_id: str) -> list[WhatIfExplorationResponse]:
        await self._require_goal(goal_id)
        runs = await self._repository.list_runs(UUID(goal_id), run_kind="impact")
        items: list[WhatIfExplorationResponse] = []
        for run in runs:
            receipt = run.receipt
            intervention = receipt.get("intervention")
            title: str | None = None
            if isinstance(intervention, dict):
                title = str(intervention.get("title") or "") or None
            if not title:
                changes = receipt.get("parsed_changes")
                if isinstance(changes, list) and changes:
                    first = changes[0]
                    if isinstance(first, dict):
                        metric = first.get("metric")
                        value = first.get("value")
                        operation = first.get("operation")
                        if metric and value is not None:
                            title = f"{operation} {metric} by {value}"
            baseline = receipt.get("raw_probability")
            scenario = receipt.get("final_expected_probability")
            conditional = receipt.get("conditional_on_full_execution_probability")
            execution = receipt.get("execution_probability")
            uplift = None
            if isinstance(baseline, int | float) and isinstance(scenario, int | float):
                uplift = (float(scenario) - float(baseline)) * 100.0
            items.append(
                WhatIfExplorationResponse(
                    id=str(run.id),
                    goal_id=str(run.goal_id),
                    run_kind=run.run_kind,
                    status=str(receipt.get("forecast_status") or ""),
                    created_at=run.created_at.isoformat() if run.created_at else None,
                    intervention_title=title,
                    baseline_probability=float(baseline)
                    if isinstance(baseline, int | float)
                    else None,
                    scenario_probability=float(scenario)
                    if isinstance(scenario, int | float)
                    else None,
                    conditional_on_execution_probability=(
                        float(conditional) if isinstance(conditional, int | float) else None
                    ),
                    execution_probability=(
                        float(execution) if isinstance(execution, int | float) else None
                    ),
                    expected_uplift_pp=uplift,
                )
            )
        return items

    async def target_search(self, request: TargetSearchRequest) -> TargetSearchResult:
        if demo_fixtures_enabled() and is_demo_goal(request.base.goal_id):
            fixture = fixture_target_search(request.base.goal_id)
            if fixture is not None:
                return fixture
        baseline = await self._simulate(
            request.base.model_copy(update={"intervention": None}), persist=False
        )
        current = baseline.baseline_probability or 0
        gap = max(0, (request.target_probability - current) * 100)
        if current + request.probability_tolerance >= request.target_probability:
            return TargetSearchResult(
                target_probability=request.target_probability,
                current_probability=current,
                gap_pp=gap,
                feasible=True,
                message="Target odds are already satisfied under the current assumptions.",
                paths=[
                    TargetPath(
                        label="No change required",
                        action_ids=[],
                        resulting_probability=current,
                        resource_cost=ResourceCost(),
                        assumptions=request.base.assumptions,
                        fragility_pp=baseline.fragility_pp,
                        valid_because=(
                            "The verified current probability clears the target tolerance."
                        ),
                        model_provenance={
                            "family": "continuous_target_transition",
                            "version": "1.0.0",
                        },
                    )
                ],
                search_method="already_satisfied",
            )
        paths = await self._discrete_target_paths(request, current)
        if request.continuous_variable is not None:
            continuous = await self._continuous_target_path(request)
            if continuous is not None:
                paths.append(continuous)
        paths.sort(key=lambda item: self._cost_score(item.resource_cost))
        result = TargetSearchResult(
            target_probability=request.target_probability,
            current_probability=current,
            gap_pp=gap,
            feasible=bool(paths),
            message=(
                "Minimum viable paths verified against the target."
                if paths
                else "Target odds are not reachable under current constraints."
            ),
            paths=paths[:3],
            search_method="bounded_enumeration_and_binary_search",
        )
        return await self._persist_target_search(request, result)

    async def action_frontier(self, request: TargetSearchRequest) -> ActionFrontierResult:
        if demo_fixtures_enabled() and is_demo_goal(request.base.goal_id):
            fixture = fixture_action_frontier(request.base.goal_id)
            if fixture is not None:
                return fixture
        baseline = await self._simulate(
            request.base.model_copy(update={"intervention": None}), persist=False
        )
        current = baseline.baseline_probability or 0
        optimizer = ActionOptimizer()
        candidates = list(request.candidates)
        if self._evidence is not None:
            evidence = await self._evidence.list_for_goal(UUID(request.base.goal_id))
            goal = await self._require_goal(request.base.goal_id)
            adjusted = []
            for action in candidates:
                context = context_from_text(
                    " ".join(
                        [action.title, action.action_type, goal.title, *goal.state_dimensions]
                    ),
                    domain=goal.state_dimensions[0] if goal.state_dimensions else "general",
                    planned_amount=action.amount,
                )
                estimate = self._behavior.estimate(evidence, goal, context)
                if estimate.usable:
                    adjusted.append(
                        action.model_copy(update={"execution_probability": estimate.probability})
                    )
                else:
                    adjusted.append(action)
            candidates = adjusted
        bundles = optimizer.enumerate(candidates, self._limits(request))
        raw: list[tuple[str, str, float, float, tuple[StructuredIntervention, ...]]] = []
        for index, bundle in enumerate(bundles):
            intervention = self._bundle_intervention(
                bundle.actions, bundle.expected_effect, bundle.cost
            )
            priced = await self._simulate(
                request.base.model_copy(update={"intervention": intervention}), persist=False
            )
            raw.append(
                (
                    f"bundle-{index}",
                    " + ".join(action.title for action in bundle.actions),
                    self._cost_score(bundle.cost),
                    ((priced.scenario_probability or current) - current) * 100,
                    bundle.actions,
                )
            )
        dominance = optimizer.pareto([(item[0], item[2], item[3]) for item in raw])
        points = [
            FrontierPoint(
                id=point_id,
                label=label,
                resource_cost=cost,
                expected_uplift_pp=uplift,
                dominated=dominance[point_id],
                action_ids=[action.id for action in actions],
                opportunity_costs=[
                    opportunity
                    for action in actions
                    for opportunity in self._opportunity_costs(action)
                ],
                assumptions=["Action effects are assumption-conditioned."],
                provenance=[
                    f"{action.id}:"
                    f"{action.effect_source.value if action.effect_source else 'UNPRICED'}"
                    for action in actions
                ],
            )
            for point_id, label, cost, uplift, actions in raw
        ]
        selected = max(
            (item for item in points if not item.dominated),
            key=lambda item: (item.expected_uplift_pp, -item.resource_cost),
            default=None,
        )
        return ActionFrontierResult(
            points=points,
            frontier_ids=[item.id for item in points if not item.dominated],
            selected_id=selected.id if selected else None,
        )

    async def possible_futures(self, request: PossibleFuturesRequest) -> ScenarioDistribution:
        if demo_fixtures_enabled() and is_demo_goal(request.goal_id):
            fixture = fixture_futures(request.goal_id)
            if fixture is not None:
                return fixture
        if any(item.weight is None for item in request.outcomes):
            resolved = await self._resolve_futures_weights(request)
            if resolved is not None:
                request = resolved
        if any(item.weight is None for item in request.outcomes):
            return ScenarioDistribution(
                outcomes=[
                    ScenarioOutcome(label=item.label, downside=item.downside)
                    for item in request.outcomes
                ],
                mutually_exclusive=request.mutually_exclusive,
                collectively_exhaustive=request.collectively_exhaustive,
                other_probability=0,
                assumptions=request.assumptions,
                evidence_basis=request.evidence_basis,
                seed=request.seed,
                model_version="multi_outcome_transition@1.0.0",
                priced=False,
                message=(
                    "Possible futures are structurally valid but unpriced. Supply explicit "
                    "or reference-derived outcome weights."
                ),
            )
        weights = [float(item.weight) for item in request.outcomes if item.weight is not None]
        named_total = sum(weights)
        other_weight = max(0.0, 1 - named_total) if request.include_other else 0
        denominator = named_total + other_weight
        if denominator <= 0:
            raise ValueError("scenario weights must contain positive mass")
        outcomes = [
            ScenarioOutcome(
                label=item.label,
                probability=float(item.weight or 0) / denominator,
                parameter_source=item.weight_source,
                median=item.median,
                p10=item.p10,
                p90=item.p90,
                downside=item.downside,
            )
            for item in request.outcomes
        ]
        distribution = ScenarioDistribution(
            outcomes=outcomes,
            mutually_exclusive=request.mutually_exclusive,
            collectively_exhaustive=request.collectively_exhaustive,
            other_probability=other_weight / denominator,
            assumptions=request.assumptions,
            evidence_basis=request.evidence_basis,
            seed=request.seed,
            model_version="multi_outcome_transition@1.0.0",
        )
        return await self._persist_distribution(request, distribution)

    async def compare_paths(self, request: PathComparisonRequest) -> PathComparisonResult:
        if demo_fixtures_enabled() and is_demo_goal(request.base.goal_id):
            fixture = fixture_compare(request.base.goal_id)
            if fixture is not None:
                return fixture
        goal = await self._require_goal(request.base.goal_id)
        budget = budget_from_goal(goal)
        items: list[PathComparisonItem] = []
        for path in request.paths:
            usage = evaluate_resource_usage(path.intervention, budget)
            priced = await self._simulate(
                request.base.model_copy(update={"intervention": path.intervention}),
                persist=False,
            )
            quantiles = priced.outcome_quantiles
            model_status = priced.status
            if not usage.within_budget:
                model_status = "EXPLORATORY_OVER_BUDGET"
            items.append(
                PathComparisonItem(
                    id=path.id,
                    label=path.label,
                    primary_goal_probability=priced.scenario_probability or 0,
                    expected_outcome=priced.expected_outcome or 0,
                    median=quantiles.get("p50", 0),
                    p10=quantiles.get("p10", 0),
                    p90=quantiles.get("p90", 0),
                    downside_probability=priced.downside_probability or 0,
                    fragility_pp=priced.fragility_pp,
                    resource_cost=path.intervention.cost,
                    execution_probability=priced.execution_probability or 0,
                    assumptions=request.base.assumptions,
                    model_status=model_status,
                    secondary_outcomes=path.secondary_outcomes,
                )
            )
        result = PathComparisonResult(
            paths=items,
            model_family="continuous_target_transition",
            model_version="1.0.0",
            seed=request.base.config.seed,
        )
        return await self._persist_path_comparison(request, result)

    async def _discrete_target_paths(
        self, request: TargetSearchRequest, current: float
    ) -> list[TargetPath]:
        bundles = ActionOptimizer().enumerate(request.candidates, self._limits(request))
        paths: list[TargetPath] = []
        for bundle in bundles:
            intervention = self._bundle_intervention(
                bundle.actions, bundle.expected_effect, bundle.cost
            )
            priced = await self._simulate(
                request.base.model_copy(update={"intervention": intervention}), persist=False
            )
            if (
                priced.scenario_probability or current
            ) + request.probability_tolerance < request.target_probability:
                continue
            verified = await self._simulate(
                request.base.model_copy(update={"intervention": intervention}), persist=False
            )
            probability = verified.scenario_probability or 0
            if probability + request.probability_tolerance < request.target_probability:
                continue
            paths.append(
                TargetPath(
                    label=" + ".join(action.title for action in bundle.actions),
                    action_ids=[action.id for action in bundle.actions],
                    resulting_probability=probability,
                    resource_cost=bundle.cost,
                    assumptions=request.base.assumptions,
                    fragility_pp=verified.fragility_pp,
                    valid_because=(
                        "Feasible bundle was re-simulated with the fixed seed and clears tolerance."
                    ),
                    model_provenance={
                        "family": "continuous_target_transition",
                        "version": "1.0.0",
                    },
                )
            )
        return paths

    async def _continuous_target_path(self, request: TargetSearchRequest) -> TargetPath | None:
        variable = request.continuous_variable
        assert variable is not None
        indexed = {item.name: item for item in request.base.assumptions}
        assumption = indexed.get(variable.assumption)
        if assumption is None:
            return None
        low, high = assumption.minimum, assumption.maximum
        best: float | None = None
        for _ in range(18):
            midpoint = (low + high) / 2
            changed = [
                item.model_copy(update={"value": midpoint})
                if item.name == assumption.name
                else item
                for item in request.base.assumptions
            ]
            priced = await self._simulate(
                request.base.model_copy(update={"assumptions": changed}), persist=False
            )
            reaches = (
                priced.scenario_probability or 0
            ) + request.probability_tolerance >= request.target_probability
            if reaches:
                best = midpoint
            if reaches == variable.increasing:
                high = midpoint
            else:
                low = midpoint
        if best is None:
            return None
        changed = [
            item.model_copy(update={"value": best}) if item.name == assumption.name else item
            for item in request.base.assumptions
        ]
        verified = await self._simulate(
            request.base.model_copy(update={"assumptions": changed}), persist=False
        )
        probability = verified.scenario_probability or 0
        if probability + request.probability_tolerance < request.target_probability:
            return None
        return TargetPath(
            label=f"Set {assumption.name.replace('_', ' ')} to {best:.4g}",
            action_ids=[],
            resulting_probability=probability,
            resource_cost=ResourceCost(),
            assumptions=changed,
            fragility_pp=verified.fragility_pp,
            valid_because=(
                "Bounded monotonic binary search converged and the result was re-simulated."
            ),
            model_provenance={
                "family": "continuous_target_transition",
                "version": "1.0.0",
            },
        )

    @staticmethod
    def _bundle_intervention(
        actions: tuple[StructuredIntervention, ...], effect: float, cost: ResourceCost
    ) -> StructuredIntervention:
        return StructuredIntervention(
            id="bundle:" + "+".join(action.id for action in actions),
            title=" + ".join(action.title for action in actions),
            action_type="bundle",
            target_dimension=actions[0].target_dimension,
            amount=1,
            unit="aggregate_effect_per_period",
            duration_periods=min(action.duration_periods for action in actions),
            effect_per_unit=effect,
            effect_source=AssumptionSource.USER,
            cost=cost,
        )

    @staticmethod
    def _limits(request: TargetSearchRequest) -> ResourceLimits:
        return ResourceLimits(
            request.limits.hours_per_week, request.limits.money, request.limits.energy
        )

    @staticmethod
    def _cost_score(cost: ResourceCost) -> float:
        return cost.hours_per_week + cost.money / 100 + cost.energy

    async def _persist(
        self, request: WhatIfRequest, result: WhatIfResult, family: str, version: str
    ) -> WhatIfResult:
        assumptions = [item.model_dump(mode="json") for item in request.assumptions]
        assumption_hash = self._hash(assumptions)
        state = {
            "current_value": request.current_value,
            "target_value": request.target_value,
            "periods": request.periods,
            "direction": request.direction,
        }
        state_hash = self._hash(state)
        request_payload = request.model_dump(mode="json")
        request_hash = self._hash({"kind": "impact", "request": request_payload})
        receipt: dict[str, object] = {
            "receipt_version": 1,
            "run_kind": "impact",
            "goal_id": request.goal_id,
            "parsed_changes": [item.model_dump(mode="json") for item in request.parsed_changes],
            "baseline_state": state,
            "intervention": request.intervention.model_dump(mode="json")
            if request.intervention
            else None,
            "assumptions": assumptions,
            "assumption_hash": assumption_hash,
            "model": {"family": family, "version": version},
            "simulation_engine_version": self._engine.version,
            "forecast_status": result.status,
            "seed": result.diagnostics.seed if result.diagnostics else request.config.seed,
            "draws": result.diagnostics.n_draws if result.diagnostics else 0,
            "convergence": result.diagnostics.model_dump(mode="json")
            if result.diagnostics
            else None,
            "raw_probability": result.baseline_probability,
            "conditional_on_full_execution_probability": (
                result.conditional_on_execution_probability
            ),
            "execution_probability": result.execution_probability,
            "final_expected_probability": result.scenario_probability,
            "quantiles": result.outcome_quantiles,
            "sensitivity": [item.model_dump(mode="json") for item in result.sensitivity],
            "fragility_pp": result.fragility_pp,
            "opportunity_cost": result.opportunity_costs,
            "critic_decision": "DETERMINISTIC_PUBLISH_EXPLORATORY",
            "llm_used": False,
        }
        if result.receipt:
            receipt["scenario"] = result.receipt
        run, created, history_created = await self._repository.append(
            goal_id=UUID(request.goal_id),
            run_kind="impact",
            request_hash=request_hash,
            state_hash=state_hash,
            assumption_hash=assumption_hash,
            model_family=family,
            model_version=version,
            status=result.status,
            receipt=receipt,
            # What If baselines are request-conditioned comparison anchors, not
            # newly published forecasts. They belong only to simulation artifacts.
            probability=None,
            evidence_watermark="",
            material_hash=None,
        )
        return result.model_copy(
            update={
                "run_id": str(run.id),
                "persisted": created,
                "history_snapshot_created": history_created,
                "receipt": receipt,
            }
        )

    async def _persist_distribution(
        self, request: PossibleFuturesRequest, result: ScenarioDistribution
    ) -> ScenarioDistribution:
        payload = request.model_dump(mode="json")
        receipt: dict[str, object] = {
            "receipt_version": 1,
            "run_kind": "possible_futures",
            "goal_id": request.goal_id,
            "scenario_distribution": result.model_dump(mode="json", exclude={"receipt"}),
            "parameter_provenance": [
                {
                    "label": item.label,
                    "source": item.weight_source.value if item.weight_source else None,
                }
                for item in request.outcomes
            ],
            "seed": request.seed,
            "llm_used": False,
            "critic_decision": "DETERMINISTIC_DISTRIBUTION_VALIDATION",
        }
        run, _, _ = await self._repository.append(
            goal_id=UUID(request.goal_id),
            run_kind="possible_futures",
            request_hash=self._hash({"kind": "possible_futures", "request": payload}),
            state_hash=self._hash({"outcomes": [item.label for item in request.outcomes]}),
            assumption_hash=self._hash(payload["assumptions"]),
            model_family="multi_outcome_transition",
            model_version="1.0.0",
            status="EXPLORATORY",
            receipt=receipt,
            probability=None,
            evidence_watermark="request:no-evidence-watermark",
            material_hash=None,
        )
        return result.model_copy(update={"run_id": str(run.id), "receipt": receipt})

    async def _persist_path_comparison(
        self, request: PathComparisonRequest, result: PathComparisonResult
    ) -> PathComparisonResult:
        payload = request.model_dump(mode="json")
        receipt: dict[str, object] = {
            "receipt_version": 1,
            "run_kind": "path_comparison",
            "goal_id": request.base.goal_id,
            "baseline_state": payload["base"],
            "paths": [item.model_dump(mode="json") for item in result.paths],
            "model": {"family": result.model_family, "version": result.model_version},
            "seed": result.seed,
            "llm_used": False,
            "critic_decision": "DETERMINISTIC_PATH_COMPARISON",
        }
        run, _, _ = await self._repository.append(
            goal_id=UUID(request.base.goal_id),
            run_kind="path_comparison",
            request_hash=self._hash({"kind": "path_comparison", "request": payload}),
            state_hash=self._hash(payload["base"]),
            assumption_hash=self._hash(payload["base"]["assumptions"]),
            model_family=result.model_family,
            model_version=result.model_version,
            status="EXPLORATORY",
            receipt=receipt,
            probability=None,
            evidence_watermark="request:no-evidence-watermark",
            material_hash=None,
        )
        return result.model_copy(update={"run_id": str(run.id), "receipt": receipt})

    async def _persist_target_search(
        self, request: TargetSearchRequest, result: TargetSearchResult
    ) -> TargetSearchResult:
        payload = request.model_dump(mode="json")
        request_hash = self._hash({"kind": "target_search", "request": payload})
        receipt: dict[str, object] = {
            "receipt_version": 1,
            "run_kind": "target_search",
            "goal_id": request.base.goal_id,
            "target_probability": request.target_probability,
            "current_probability": result.current_probability,
            "paths": [item.model_dump(mode="json") for item in result.paths],
            "optimizer_constraints": request.limits.model_dump(mode="json"),
            "target_search_method": result.search_method,
            "seed": request.base.config.seed,
            "llm_used": False,
            "critic_decision": "DETERMINISTIC_SEARCH",
        }
        run, _, _ = await self._repository.append(
            goal_id=UUID(request.base.goal_id),
            run_kind="target_search",
            request_hash=request_hash,
            state_hash=self._hash(payload["base"]),
            assumption_hash=self._hash(payload["base"]["assumptions"]),
            model_family="continuous_target_transition",
            model_version="1.0.0",
            status="FEASIBLE" if result.feasible else "UNREACHABLE",
            receipt=receipt,
            probability=None,
            evidence_watermark="request:no-evidence-watermark",
            material_hash=None,
        )
        return result.model_copy(update={"run_id": str(run.id), "receipt": receipt})

    async def _resolve_futures_weights(
        self, request: PossibleFuturesRequest
    ) -> PossibleFuturesRequest | None:
        if self._evidence is None:
            return None
        goal = await self._require_goal(request.goal_id)
        evidence = await self._evidence.list_for_goal(UUID(request.goal_id))
        labels = [item.label for item in request.outcomes]
        resolved = resolve_futures_weights(
            goal,
            evidence,
            scenario_labels=labels,
            seed=request.seed,
        )
        if resolved is None:
            return None
        by_label = {item.label: item for item in resolved.outcomes}
        outcomes = []
        for item in request.outcomes:
            mapped = by_label.get(item.label)
            if mapped is None:
                continue
            outcomes.append(
                item.model_copy(
                    update={
                        "weight": mapped.weight,
                        "weight_source": mapped.weight_source,
                        "median": mapped.median,
                        "p10": mapped.p10,
                        "p90": mapped.p90,
                    }
                )
            )
        if not outcomes:
            return None
        basis = list(request.evidence_basis)
        for entry in resolved.evidence_basis:
            if entry not in basis:
                basis.append(entry)
        return request.model_copy(update={"outcomes": outcomes, "evidence_basis": basis})

    def _apply_behavior_execution(
        self,
        goal: GoalContract,
        request: WhatIfRequest,
        evidence: list,
        commitment_trials: list | None = None,
    ) -> WhatIfRequest:
        self._last_behavior_profile = None
        incoming = next(
            (item for item in request.assumptions if item.name == "execution_probability"), None
        )
        if (
            incoming is not None
            and incoming.source == "USER_ASSUMPTION"
            and abs(incoming.value - 0.72) > 1e-6
        ):
            return request
        if not evidence and not commitment_trials:
            return request
        intervention = request.intervention
        context = context_from_text(
            " ".join(
                [
                    intervention.title if intervention else "",
                    intervention.action_type if intervention else "",
                    goal.title,
                    *goal.state_dimensions,
                ]
            ),
            domain=goal.state_dimensions[0] if goal.state_dimensions else "general",
            planned_amount=intervention.amount if intervention else None,
        )
        profile = self._behavior.profile_from_evidence(
            evidence, goal, context, commitment_trials=commitment_trials
        )
        self._last_behavior_profile = profile
        if not profile.execution.usable:
            return request
        updated = []
        replaced = False
        for item in request.assumptions:
            if item.name == "execution_probability":
                updated.append(
                    item.model_copy(
                        update={
                            "value": profile.execution.probability,
                            "source": "FITTED",
                            "provenance": f"behavior:{profile.estimator_version}",
                        }
                    )
                )
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            return request
        return request.model_copy(update={"assumptions": updated})

    @staticmethod
    def _hash(value: object) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _opportunity_costs(intervention: object) -> list[str]:
        cost = intervention.cost  # type: ignore[attr-defined]
        costs = []
        if cost.hours_per_week:
            costs.append(f"{cost.hours_per_week:g} hours/week displaced")
        if cost.money:
            costs.append(f"{cost.money:g} monetary units committed")
        if cost.energy:
            costs.append(f"{cost.energy:g} energy units committed")
        return costs

    @staticmethod
    def _fan(trajectories: np.ndarray) -> list[dict[str, float]]:
        quantiles = np.quantile(trajectories, [0.1, 0.5, 0.9], axis=0)
        return [
            {
                "period": float(period),
                "p10": float(quantiles[0, period]),
                "p50": float(quantiles[1, period]),
                "p90": float(quantiles[2, period]),
            }
            for period in range(trajectories.shape[1])
        ]
