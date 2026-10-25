"""Reverse-mode search: price lever settings and action bundles through the engine.

Every lever setting is priced exactly as Compare prices it: the base assumptions stay
at today's evidence and the setting is a parsed scenario change, so the result is
discounted by modeled follow-through. Settings are snapped to the lever's step.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from personal_markets.what_if.domain import (
    Assumption,
    BlueprintAction,
    InterventionChangeInput,
    ResourceCost,
    StructuredIntervention,
    TargetPath,
    TargetSearchRequest,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import apply_parsed_changes_to_assumptions
from personal_markets.what_if.optimizer import ActionBundle, ActionOptimizer, ResourceLimits
from personal_markets.what_if.reverse_blueprint import (
    LeverScan,
    LeverSetting,
    LeverSpec,
    PricedOption,
    ScanPoint,
)

REVERSE_LEVER_NAMES = ("flow", "weekly_application_rate")
# Shares of the distance from today's value to the improving bound priced for the scan.
# The bound itself is always priced, since it fixes the lever's direction.
SCAN_FRACTIONS = (0.1, 0.25, 0.5, 0.75)
MODEL_PROVENANCE = {"family": "continuous_target_transition", "version": "1.0.0"}

Simulate = Callable[[WhatIfRequest], Awaitable[WhatIfResult]]
BundleIntervention = Callable[
    [tuple[StructuredIntervention, ...], float, ResourceCost], StructuredIntervention
]


def target_lever_label(assumption: Assumption | LeverSpec, value: float) -> str:
    name = assumption.lever_id if isinstance(assumption, LeverSpec) else assumption.name
    if name == "flow" and assumption.unit == "currency/month":
        return f"Contribute {value:,.0f} each month"
    if name == "flow" and assumption.unit == "seconds/week":
        return f"Change weekly pace trend to {value:,.1f} seconds"
    if name == "weekly_application_rate":
        return f"Submit {value:,.0f} applications each week"
    return f"Set {name.replace('_', ' ')} to {value:.4g} {assumption.unit}"


def snap(lever: LeverSpec, value: float) -> float:
    clamped = min(lever.maximum, max(lever.minimum, value))
    return round(round(clamped / lever.step) * lever.step, 10)


@dataclass(frozen=True, slots=True)
class PricedBundle:
    bundle: ActionBundle
    intervention: StructuredIntervention
    actions: tuple[BlueprintAction, ...]
    probability: float


class ReverseSearch:
    def __init__(
        self,
        *,
        simulate: Simulate,
        bundle_intervention: BundleIntervention,
        limits: ResourceLimits,
        request: TargetSearchRequest,
        current: float,
    ) -> None:
        self._simulate = simulate
        self._bundle_intervention = bundle_intervention
        self._limits = limits
        self._request = request
        self._current = current
        self._cache: dict[tuple[object, ...], WhatIfResult] = {}
        self._paths: list[TargetPath] = []
        self.options: list[PricedOption] = []
        self.follow_through: float | None = None

    def _reaches(self, probability: float) -> bool:
        return probability + self._request.probability_tolerance >= self._request.target_probability

    def _changes(self, settings: tuple[LeverSetting, ...]) -> list[InterventionChangeInput]:
        return [
            InterventionChangeInput(
                metric=item.lever.lever_id,
                operation="set",
                value=item.value,
                unit=item.lever.unit,
                provenance="EXPLORATION_ASSUMPTION",
            )
            for item in settings
        ]

    async def _price(
        self, settings: tuple[LeverSetting, ...], intervention: StructuredIntervention | None
    ) -> WhatIfResult:
        key = (
            tuple((item.lever.lever_id, item.value) for item in settings),
            intervention.id if intervention else None,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._simulate(
            self._request.base.model_copy(
                update={"parsed_changes": self._changes(settings), "intervention": intervention}
            )
        )
        self._cache[key] = result
        if settings and self.follow_through is None and result.execution_probability is not None:
            self.follow_through = result.execution_probability
        return result

    def _record(
        self,
        *,
        label: str,
        action_ids: list[str],
        probability: float,
        cost: ResourceCost,
        settings: tuple[LeverSetting, ...],
        result: WhatIfResult,
        valid_because: str,
    ) -> None:
        if not self._reaches(probability):
            return
        assumptions = self._request.base.assumptions
        if settings:
            assumptions = apply_parsed_changes_to_assumptions(
                assumptions,
                [
                    InterventionChangeResponse.model_validate(change.model_dump())
                    for change in self._changes(settings)
                ],
            )
        self._paths.append(
            TargetPath(
                label=label,
                action_ids=action_ids,
                resulting_probability=probability,
                resource_cost=cost,
                assumptions=assumptions,
                fragility_pp=result.fragility_pp,
                valid_because=valid_because,
                model_provenance=dict(MODEL_PROVENANCE),
            )
        )

    def feasible_paths(self) -> list[TargetPath]:
        return list(self._paths)

    async def price_bundles(self) -> list[PricedBundle]:
        priced: list[PricedBundle] = []
        for bundle in ActionOptimizer().enumerate(self._request.candidates, self._limits):
            intervention = self._bundle_intervention(
                bundle.actions, bundle.expected_effect, bundle.cost
            )
            result = await self._price((), intervention)
            probability = result.scenario_probability
            if probability is None:
                continue
            actions = tuple(
                BlueprintAction(
                    action_id=action.id,
                    title=action.title,
                    hours_per_week=action.cost.hours_per_week,
                    money=action.cost.money,
                )
                for action in bundle.actions
            )
            self.options.append(
                PricedOption(id=intervention.id, probability=probability, actions=actions)
            )
            self._record(
                label=" + ".join(action.title for action in bundle.actions),
                action_ids=[action.id for action in bundle.actions],
                probability=probability,
                cost=bundle.cost,
                settings=(),
                result=result,
                valid_because="Feasible bundle priced with the fixed seed clears tolerance.",
            )
            priced.append(PricedBundle(bundle, intervention, actions, probability))
        return priced

    async def scan(self, lever: LeverSpec) -> LeverScan:
        """Price the lever toward whichever bound the model says raises the odds."""
        low = await self._price((LeverSetting(lever, snap(lever, lever.minimum)),), None)
        high = await self._price((LeverSetting(lever, snap(lever, lever.maximum)),), None)
        if low.scenario_probability is None and high.scenario_probability is None:
            return LeverScan(lever, ())
        increasing = (high.scenario_probability or 0) >= (low.scenario_probability or 0)
        spec = replace(lever, increasing=increasing)
        bound = snap(spec, spec.maximum if increasing else spec.minimum)
        points = [ScanPoint(spec.baseline, self._current)]
        values = sorted(
            {snap(spec, spec.baseline + (bound - spec.baseline) * f) for f in SCAN_FRACTIONS}
            | {bound},
            reverse=not increasing,
        )
        for value in values:
            if abs(value - spec.baseline) < spec.step / 2:
                continue
            result = await self._price((LeverSetting(spec, value),), None)
            if result.scenario_probability is None:
                continue
            conditional = result.conditional_on_execution_probability
            points.append(ScanPoint(value, result.scenario_probability, conditional))
            self.options.append(
                PricedOption(
                    id=f"lever:{spec.lever_id}:{value:g}",
                    probability=result.scenario_probability,
                    settings=(LeverSetting(spec, value),),
                    conditional=conditional,
                )
            )
        return LeverScan(spec, tuple(points))

    async def _smallest_reaching(
        self,
        lever: LeverSpec,
        start: float,
        end: float,
        intervention: StructuredIntervention | None,
        end_result: WhatIfResult,
    ) -> tuple[float, WhatIfResult]:
        """Binary search the step grid in (start, end]; `end` is known to reach."""
        direction = 1 if end >= start else -1
        steps = round(abs(end - start) / lever.step)
        low, high, found = 0, steps, end_result
        while high - low > 1:
            middle = (low + high) // 2
            value = snap(lever, start + direction * middle * lever.step)
            result = await self._price((LeverSetting(lever, value),), intervention)
            if result.scenario_probability is not None and self._reaches(
                result.scenario_probability
            ):
                high, found = middle, result
            else:
                low = middle
        return snap(lever, start + direction * high * lever.step), found

    async def solve_levers(self, scans: list[LeverScan]) -> list[LeverScan]:
        """Smallest step-snapped setting of each lever alone that reaches the target."""
        solved: list[LeverScan] = []
        for scan in scans:
            points = list(scan.points)
            index = next(
                (i for i, point in enumerate(points) if i and self._reaches(point.probability)),
                None,
            )
            if index is None:
                solved.append(scan)
                continue
            lever = scan.lever
            end = points[index]
            value, result = await self._smallest_reaching(
                lever,
                points[index - 1].value,
                end.value,
                None,
                await self._price((LeverSetting(lever, end.value),), None),
            )
            probability = result.scenario_probability
            assert probability is not None
            setting = (LeverSetting(lever, value),)
            self.options.append(
                PricedOption(
                    id=f"lever-solve:{lever.lever_id}:{value:g}",
                    probability=probability,
                    settings=setting,
                    conditional=result.conditional_on_execution_probability,
                )
            )
            self._record(
                label=target_lever_label(lever, value),
                action_ids=[],
                probability=probability,
                cost=ResourceCost(),
                settings=setting,
                result=result,
                valid_because=(
                    "Smallest step-snapped setting that clears the target, priced with "
                    "follow-through exactly like Compare."
                ),
            )
            if all(abs(point.value - value) > lever.step / 2 for point in points):
                points.append(
                    ScanPoint(value, probability, result.conditional_on_execution_probability)
                )
            solved.append(LeverScan(lever, tuple(points)))
        return solved

    async def combine(self, scans: list[LeverScan], bundles: list[PricedBundle]) -> None:
        """Strongest affordable bundle plus the smallest lever move that closes the gap."""
        if not bundles:
            return
        best = max(bundles, key=lambda item: item.probability)
        if self._reaches(best.probability):
            return
        for scan in scans:
            if len(scan.points) < 2:
                continue
            lever = scan.lever
            bound = snap(lever, lever.maximum if lever.increasing else lever.minimum)
            at_bound = await self._price((LeverSetting(lever, bound),), best.intervention)
            if at_bound.scenario_probability is None:
                continue
            value, result = bound, at_bound
            if self._reaches(at_bound.scenario_probability):
                value, result = await self._smallest_reaching(
                    lever, lever.baseline, bound, best.intervention, at_bound
                )
            probability = result.scenario_probability
            assert probability is not None
            setting = (LeverSetting(lever, value),)
            self.options.append(
                PricedOption(
                    id=f"combo:{best.intervention.id}:{lever.lever_id}:{value:g}",
                    probability=probability,
                    settings=setting,
                    actions=best.actions,
                    conditional=result.conditional_on_execution_probability,
                )
            )
            self._record(
                label=" + ".join(
                    [*(action.title for action in best.actions), target_lever_label(lever, value)]
                ),
                action_ids=[action.action_id for action in best.actions],
                probability=probability,
                cost=best.bundle.cost,
                settings=setting,
                result=result,
                valid_because=(
                    "Bundle plus the smallest lever setting that clears the target, "
                    "priced together in one run."
                ),
            )
