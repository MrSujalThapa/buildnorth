"""Reverse-mode search: price lever settings and action bundles through the engine.

Every lever setting is priced exactly as Compare prices it: the base assumptions stay
at today's evidence and the setting is a parsed scenario change, so the result is
discounted by modeled follow-through. Settings are snapped to the lever's step.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace

from personal_markets.forecasting.families import AssumptionSource
from personal_markets.what_if.domain import (
    Assumption,
    BlueprintAction,
    BlueprintExcludedParameter,
    BlueprintUnpricedRecommendation,
    InterventionChangeInput,
    ResourceCost,
    StructuredIntervention,
    TargetPath,
    TargetSearchRequest,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.intervention_overrides import (
    apply_parsed_changes_to_assumptions,
    unmapped_change_metrics,
)
from personal_markets.what_if.intervention_registry import KNOWN_METRICS
from personal_markets.what_if.optimizer import ActionBundle, ActionOptimizer, ResourceLimits
from personal_markets.what_if.reverse_blueprint import (
    LeverKind,
    LeverScan,
    LeverSetting,
    LeverSpec,
    PricedOption,
    ScanPoint,
    effort_score,
    format_lever_value,
    lever_label,
)

# Lever classification by assumption scope. Behavioral volume is something the user
# does more or less of; conversion scopes are rates the user can only influence
# indirectly and must back with evidence. Everything else is not searched.
BEHAVIORAL_VOLUME_SCOPES = frozenset(
    {"pipeline_activity", "monthly_flow", "training_trend", "composed_rate"}
)
CONVERSION_SCOPES = frozenset({"stage_conversion"})
ENVIRONMENT_SCOPES = frozenset({"return_assumption", "volatility", "shock_assumption"})
EXECUTION_SCOPE = "execution"
# Clients that send assumptions without scope metadata get the model's default scope;
# only these volume levers are recognised by name in that case.
UNSCOPED = "simulation"
UNSCOPED_VOLUME_LEVER_NAMES = frozenset({"flow", "weekly_application_rate"})
EXECUTION_ASSUMPTION = "execution_probability"
# Search bound for conversion rates: at most +50% relative to today's value. The hiring
# reference publishes point priors only, no ranges, so this is a search bound chosen
# to keep plans plausible. It is not evidence that a lift this large is achievable.
MAX_CONVERSION_RELATIVE_LIFT = 0.5
CONVERSION_BOUND_SOURCE = (
    "search bound of +50% relative to today's rate (the reference has no published "
    "range); a bound on the search, not evidence"
)
# Composed specs carry no slider range for `node.rate`. Search up to this multiple of
# today's estimated rate, on this many grid steps. Search bounds, not evidence.
COMPOSED_RATE_MAX_MULTIPLE = 4.0
COMPOSED_RATE_GRID_STEPS = 40
COMPOSED_BOUND_SOURCE = (
    "search bound of 4x today's estimated rate (composed models publish no range); "
    "a bound on the search, not evidence"
)
# Combination search: each greedy move raises one lever by this share of its searchable
# range, a plan changes at most MAX_PLAN_LEVERS levers, and a move must add at least
# MIN_COMBINATION_GAIN (0.1 pp) of modeled odds to count.
COMBINATION_LEVELS = 4
MAX_PLAN_LEVERS = 3
MIN_COMBINATION_GAIN = 0.001
_EFFORT_FLOOR = 1e-9
# Shares of the distance from today's value to the improving bound priced for the scan.
# The bound itself is always priced, since it fixes the lever's direction.
SCAN_FRACTIONS = (0.1, 0.25, 0.5, 0.75)
CONVERSION_SCAN_FRACTIONS = (0.5,)
MODEL_PROVENANCE = {"family": "continuous_target_transition", "version": "1.0.0"}
# Known metrics that are outcomes or model internals rather than actions a person takes.
NON_ACTION_METRICS = frozenset({"flow", "net_worth", "10k_time_seconds"})
# Known metrics that restate a searched lever in another unit; listing them as unpriced
# would contradict the priced lever.
RESTATED_LEVERS: dict[str, str] = {
    "applications_per_month": "weekly_application_rate",
    "monthly_contribution": "flow",
    "contribution_per_month": "flow",
}


def classify_lever(assumption: Assumption) -> LeverKind | None:
    """Searchable lever kind for an assumption, or None if Reverse must not move it."""
    if exclusion_reason(assumption) is not None:
        return None
    if assumption.scope in CONVERSION_SCOPES:
        return "conversion"
    return "behavioral_volume"


def exclusion_reason(assumption: Assumption) -> str | None:
    if assumption.name == EXECUTION_ASSUMPTION or assumption.scope == EXECUTION_SCOPE:
        return "Follow-through is estimated from behavior, never searched as a lever."
    if assumption.scope in ENVIRONMENT_SCOPES:
        return "Market or environment parameter; not under your control."
    if not assumption.editable:
        return "Fixed by the goal or evidence; not editable."
    unscoped_volume = (
        assumption.scope == UNSCOPED and assumption.name in UNSCOPED_VOLUME_LEVER_NAMES
    )
    if assumption.scope not in BEHAVIORAL_VOLUME_SCOPES | CONVERSION_SCOPES and not (
        unscoped_volume
    ):
        return "Not a user-controllable lever the model can search."
    if assumption.maximum <= assumption.minimum:
        return "No searchable range."
    return None


def lever_spec(assumption: Assumption, kind: LeverKind) -> LeverSpec:
    if kind == "conversion":
        cap = min(assumption.maximum, assumption.value * (1 + MAX_CONVERSION_RELATIVE_LIFT))
        steps = max(0, math.floor((cap - assumption.value) / assumption.step + 1e-9))
        return LeverSpec(
            lever_id=assumption.name,
            unit=assumption.unit,
            baseline=assumption.value,
            minimum=assumption.value,
            maximum=round(assumption.value + steps * assumption.step, 10),
            step=assumption.step,
            kind=kind,
            label=assumption.description or None,
            origin=assumption.value,
            bound_source=CONVERSION_BOUND_SOURCE,
        )
    composed = assumption.scope == "composed_rate"
    return LeverSpec(
        lever_id=assumption.name,
        unit=assumption.unit,
        baseline=assumption.value,
        minimum=assumption.minimum,
        maximum=assumption.maximum,
        step=assumption.step,
        kind=kind,
        label=(assumption.description or None) if composed else None,
        origin=assumption.value if composed else 0.0,
        bound_source=COMPOSED_BOUND_SOURCE if composed else "Assumption range from the model.",
    )


@dataclass(frozen=True, slots=True)
class LeverSelection:
    levers: tuple[LeverSpec, ...]
    excluded: tuple[BlueprintExcludedParameter, ...]


def select_levers(assumptions: Iterable[Assumption]) -> LeverSelection:
    levers: list[LeverSpec] = []
    excluded: list[BlueprintExcludedParameter] = []
    seen: set[str] = set()
    for assumption in assumptions:
        if assumption.name in seen:
            continue
        seen.add(assumption.name)
        kind = classify_lever(assumption)
        if kind is None:
            reason = exclusion_reason(assumption)
            assert reason is not None
            excluded.append(BlueprintExcludedParameter(name=assumption.name, reason=reason))
            continue
        spec = lever_spec(assumption, kind)
        if spec.maximum - spec.minimum < spec.step / 2:
            excluded.append(
                BlueprintExcludedParameter(name=assumption.name, reason="No searchable range.")
            )
            continue
        levers.append(spec)
    return LeverSelection(tuple(levers), tuple(excluded))


def composed_rate_assumptions(
    units: Mapping[str, str], values: Mapping[str, object]
) -> list[Assumption]:
    """Slider-shaped assumptions for a composed spec's priceable `node.rate` parameters."""
    items: list[Assumption] = []
    for name, unit in units.items():
        if not name.endswith(".rate"):
            continue
        raw = values.get(name)
        if not isinstance(raw, int | float) or raw <= 0:
            continue
        value = float(raw)
        maximum = value * COMPOSED_RATE_MAX_MULTIPLE
        node = name.split(".", 1)[0].replace("_", " ")
        items.append(
            Assumption(
                name=name,
                description=f"{node} rate",
                value=value,
                minimum=0.0,
                maximum=maximum,
                step=maximum / COMPOSED_RATE_GRID_STEPS,
                source=AssumptionSource.FITTED,
                unit=unit,
                provenance="Composed model parameter estimated from dated evidence.",
                editable=True,
                scope="composed_rate",
            )
        )
    return items


def unpriced_recommendations(
    domain: str, assumption_names: set[str], searched: set[str]
) -> list[BlueprintUnpricedRecommendation]:
    """Known actions for the goal's domain that map to no modeled assumption."""
    metrics = sorted(KNOWN_METRICS.get(domain, set()) - NON_ACTION_METRICS)
    unmapped = unmapped_change_metrics(assumption_names, metrics)
    items: list[BlueprintUnpricedRecommendation] = []
    for metric in unmapped:
        if RESTATED_LEVERS.get(metric) in searched:
            continue
        label = metric.replace("_", " ")
        label = label[:1].upper() + label[1:]
        items.append(
            BlueprintUnpricedRecommendation(
                metric=metric,
                label=label,
                measurement=(
                    f"Log {label.lower()} as dated evidence. The model has no link from it "
                    "to a modeled rate yet, so it is not priced."
                ),
            )
        )
    return items

Simulate = Callable[[WhatIfRequest], Awaitable[WhatIfResult]]
BundleIntervention = Callable[
    [tuple[StructuredIntervention, ...], float, ResourceCost], StructuredIntervention
]


def target_lever_label(assumption: Assumption | LeverSpec, value: float) -> str:
    name = assumption.lever_id if isinstance(assumption, LeverSpec) else assumption.name
    if isinstance(assumption, LeverSpec) and assumption.kind == "conversion":
        return f"Reach {lever_label(assumption).lower()} of {format_lever_value(assumption, value)}"
    if name == "flow" and assumption.unit == "currency/month":
        return f"Contribute {value:,.0f} each month"
    if name == "flow" and assumption.unit == "seconds/week":
        return f"Change weekly pace trend to {value:,.1f} seconds"
    if name == "weekly_application_rate":
        return f"Submit {value:,.0f} applications each week"
    if isinstance(assumption, LeverSpec):
        return f"Set {lever_label(assumption).lower()} to {format_lever_value(assumption, value)}"
    return f"Set {name.replace('_', ' ')} to {value:.4g} {assumption.unit}"


def snap(lever: LeverSpec, value: float) -> float:
    """Nearest grid point `origin + k * step` that stays inside the lever's range."""
    clamped = min(lever.maximum, max(lever.minimum, value))
    snapped = lever.origin + round((clamped - lever.origin) / lever.step) * lever.step
    if snapped > lever.maximum + 1e-9:
        snapped -= lever.step
    if snapped < lever.minimum - 1e-9:
        snapped += lever.step
    return round(snapped, 10)


class _Climb:
    """Greedy ascent over lever ladders, by modeled odds gained per unit of effort."""

    def __init__(self, search: ReverseSearch, levers: list[LeverSpec]) -> None:
        self._search = search
        self.by_id = {lever.lever_id: lever for lever in levers}
        self.ladders = {lever.lever_id: search._ladder(lever) for lever in levers}

    def settings(self, state: Mapping[str, int]) -> tuple[LeverSetting, ...]:
        return tuple(
            LeverSetting(self.by_id[lever_id], self.ladders[lever_id][index])
            for lever_id, index in state.items()
        )

    def _effort(self, state: Mapping[str, int]) -> float:
        return effort_score(PricedOption(id="", probability=0.0, settings=self.settings(state)))

    async def run(
        self, state: dict[str, int], levers: list[LeverSpec], *, limit: int | None = None
    ) -> dict[str, int]:
        search = self._search
        if state:
            start = await search._price(self.settings(state), None)
            probability = start.scenario_probability or search._current
        else:
            probability = search._current
        effort = self._effort(state)
        while not search._reaches(probability):
            best: tuple[float, dict[str, int], float, float] | None = None
            for lever in levers:
                index = state.get(lever.lever_id, -1) + 1
                if index >= len(self.ladders[lever.lever_id]):
                    continue
                if limit is not None and lever.lever_id not in state and len(state) >= limit:
                    continue
                trial = {**state, lever.lever_id: index}
                priced = await search._price(self.settings(trial), None)
                value = priced.scenario_probability
                if value is None or value - probability < MIN_COMBINATION_GAIN:
                    continue
                cost = self._effort(trial)
                ratio = (value - probability) / max(cost - effort, _EFFORT_FLOOR)
                if best is None or ratio > best[0]:
                    best = (ratio, trial, value, cost)
            if best is None:
                break
            _, state, probability, effort = best
        return state


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
            tuple(sorted((item.lever.lever_id, item.value) for item in settings)),
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
        """Price the lever toward whichever bound the model says raises the odds.

        Conversion levers are searched upward only (their range starts at today's
        rate), so their direction needs no pricing and a coarser scan suffices.
        """
        high = await self._price((LeverSetting(lever, snap(lever, lever.maximum)),), None)
        fractions: tuple[float, ...] = SCAN_FRACTIONS
        if lever.kind == "conversion":
            if high.scenario_probability is None:
                return LeverScan(lever, ())
            increasing = True
            fractions = CONVERSION_SCAN_FRACTIONS
        else:
            low = await self._price((LeverSetting(lever, snap(lever, lever.minimum)),), None)
            if low.scenario_probability is None and high.scenario_probability is None:
                return LeverScan(lever, ())
            increasing = (high.scenario_probability or 0) >= (low.scenario_probability or 0)
        spec = replace(lever, increasing=increasing)
        bound = snap(spec, spec.maximum if increasing else spec.minimum)
        points = [ScanPoint(spec.baseline, self._current)]
        values = sorted(
            {snap(spec, spec.baseline + (bound - spec.baseline) * f) for f in fractions}
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
        others: tuple[LeverSetting, ...] = (),
    ) -> tuple[float, WhatIfResult]:
        """Binary search the step grid in (start, end]; `end` is known to reach."""
        direction = 1 if end >= start else -1
        steps = round(abs(end - start) / lever.step)
        low, high, found = 0, steps, end_result
        while high - low > 1:
            middle = (low + high) // 2
            value = snap(lever, start + direction * middle * lever.step)
            result = await self._price((*others, LeverSetting(lever, value)), intervention)
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

    @staticmethod
    def _ladder(lever: LeverSpec) -> list[float]:
        bound = snap(lever, lever.maximum if lever.increasing else lever.minimum)
        values: list[float] = []
        for level in range(1, COMBINATION_LEVELS + 1):
            share = level / COMBINATION_LEVELS
            value = snap(lever, lever.baseline + (bound - lever.baseline) * share)
            if abs(value - lever.baseline) >= lever.step / 2 and value not in values:
                values.append(value)
        return values

    def _add_combination(
        self, settings: tuple[LeverSetting, ...], result: WhatIfResult, *, record: bool
    ) -> None:
        probability = result.scenario_probability
        if probability is None:
            return
        self.options.append(
            PricedOption(
                id="levers:" + ",".join(f"{s.lever.lever_id}={s.value:g}" for s in settings),
                probability=probability,
                settings=settings,
                conditional=result.conditional_on_execution_probability,
            )
        )
        if record:
            self._record(
                label=" + ".join(target_lever_label(s.lever, s.value) for s in settings),
                action_ids=[],
                probability=probability,
                cost=ResourceCost(),
                settings=settings,
                result=result,
                valid_because=(
                    "Cheapest lever combination found that clears the target, priced in one "
                    "run with follow-through exactly like Compare."
                ),
            )

    async def combine_levers(self, scans: list[LeverScan]) -> None:
        """Greedy multi-lever plan: each move buys the most modeled odds per unit of effort.

        A move raises one lever by 1/COMBINATION_LEVELS of its searchable range, and a
        plan changes at most MAX_PLAN_LEVERS levers. Two climbs run: one open to every
        lever and one over a focused subset. A plan that reaches the target has each
        lever trimmed to the smallest step-snapped value (or dropped) that still reaches
        with the others held. Each final plan is a priced option, so an unreachable
        target still reports the highest modeled combination.
        """
        usable = [
            scan.lever
            for scan in scans
            if len(scan.points) >= 2
            and max(point.probability for point in scan.points)
            >= self._current + MIN_COMBINATION_GAIN
        ]
        if len(usable) < 2:
            return
        climb = _Climb(self, usable)
        state = await climb.run({}, usable, limit=MAX_PLAN_LEVERS)
        # A second climb restricted to direct behaviors plus the conversion levers with
        # the largest single-lever gain: the open climb can fill its lever slots with
        # cheap early moves and strand the plan on the wrong subset.
        best_gain = {
            scan.lever.lever_id: max(point.probability for point in scan.points)
            for scan in scans
            if scan.lever.lever_id in climb.by_id
        }
        focused = sorted(
            usable,
            key=lambda lever: (lever.kind != "behavioral_volume", -best_gain[lever.lever_id]),
        )[:MAX_PLAN_LEVERS]
        plans = [state, await climb.run({}, focused)]
        seen: set[tuple[tuple[str, int], ...]] = set()
        for plan in plans:
            key = tuple(sorted(plan.items()))
            if len(plan) < 2 or key in seen:
                continue
            seen.add(key)
            result = await self._price(climb.settings(plan), None)
            probability = result.scenario_probability
            if probability is None:
                continue
            self._add_combination(climb.settings(plan), result, record=False)
            if self._reaches(probability):
                await self._trim(list(climb.settings(plan)), result)

    async def _trim(self, settings: list[LeverSetting], result: WhatIfResult) -> None:
        for index in range(len(settings)):
            setting = settings[index]
            lever = setting.lever
            others = tuple(item for i, item in enumerate(settings) if i != index)
            if abs(setting.value - lever.baseline) < lever.step / 2:
                continue
            without = await self._price(others, None) if others else None
            if (
                without is not None
                and without.scenario_probability is not None
                and self._reaches(without.scenario_probability)
            ):
                settings[index] = LeverSetting(lever, lever.baseline)
                result = without
                continue
            value, trimmed = await self._smallest_reaching(
                lever, lever.baseline, setting.value, None, result, others
            )
            settings[index] = LeverSetting(lever, value)
            result = trimmed
        final = tuple(
            item
            for item in settings
            if abs(item.value - item.lever.baseline) >= item.lever.step / 2
        )
        self._add_combination(final, result, record=True)
