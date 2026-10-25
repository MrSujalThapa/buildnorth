"""Reverse-mode blueprint: turn engine-priced options into one recommended path.

Pure functions only. Every probability passed in comes from the simulation engine;
this module ranks, deduplicates, explains plateaus, and renders template text from
lever metadata. It never produces a probability of its own; the follow-through mixture
bound `b + f * (1 - b)` is used only to name a plateau's cause and is not reported.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from personal_markets.what_if.domain import (
    BlueprintAction,
    BlueprintAlternative,
    BlueprintLeverChange,
    BlueprintPlateau,
    EffortLevel,
    ReverseBlueprint,
)

# Relative change vs. today's lever value (0.5 = +50%) that bounds each effort level.
EFFORT_LIGHT_MAX_RATIO = 0.5
EFFORT_MODERATE_MAX_RATIO = 1.5
# Same bounds as a share of the lever's remaining modeled range, used when today's value
# is zero or too small for a ratio to mean anything.
EFFORT_LIGHT_MAX_RANGE = 0.25
EFFORT_MODERATE_MAX_RANGE = 0.6
# Using this share of the remaining range is heavy regardless of the ratio.
EFFORT_HEAVY_RANGE = 0.75
# Settings at or past this share of the range sit near the model bound.
NEAR_BOUND_RANGE = 0.9
# One weekly hour or one unit of money expressed in lever-ratio effort units.
ACTION_HOURS_PER_EFFORT_UNIT = 10.0
ACTION_MONEY_PER_EFFORT_UNIT = 1000.0
# Options whose odds differ by no more than this are the same answer (0.5 pp).
DEDUPE_TOLERANCE = 0.005
# Remaining gain below this (1 pp) across the rest of a lever's range is a plateau.
PLATEAU_GAIN_TOLERANCE = 0.01
# A plateau within this distance (3 pp) of the follow-through ceiling is caused by it.
FOLLOW_THROUGH_CAP_MARGIN = 0.03
# Conditional-on-execution odds at or above this mean the lever itself is saturated.
SATURATED_CONDITIONAL = 0.97
MAX_ALTERNATIVES = 5


@dataclass(frozen=True, slots=True)
class LeverSpec:
    lever_id: str
    unit: str
    baseline: float
    minimum: float
    maximum: float
    step: float
    increasing: bool = True


@dataclass(frozen=True, slots=True)
class LeverSetting:
    lever: LeverSpec
    value: float


@dataclass(frozen=True, slots=True)
class ScanPoint:
    value: float
    probability: float
    conditional: float | None = None


@dataclass(frozen=True, slots=True)
class PricedOption:
    id: str
    probability: float
    settings: tuple[LeverSetting, ...] = ()
    actions: tuple[BlueprintAction, ...] = ()
    conditional: float | None = None


@dataclass(frozen=True, slots=True)
class LeverScan:
    lever: LeverSpec
    points: tuple[ScanPoint, ...]


@dataclass(frozen=True, slots=True)
class BlueprintInputs:
    target: float
    baseline: float
    tolerance: float
    options: tuple[PricedOption, ...] = ()
    scans: tuple[LeverScan, ...] = ()
    follow_through: float | None = None
    levers: tuple[LeverSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class _LeverCopy:
    noun: str
    unit_label: str
    currency: bool = False


def _lever_copy(lever: LeverSpec) -> _LeverCopy:
    if lever.lever_id == "weekly_application_rate":
        return _LeverCopy("weekly applications", "applications/week")
    if lever.lever_id == "flow" and lever.unit.startswith("currency"):
        return _LeverCopy("monthly contribution", "/month", currency=True)
    if lever.lever_id == "flow" and lever.unit == "seconds/week":
        return _LeverCopy("weekly pace trend", "s/week")
    return _LeverCopy(lever.lever_id.replace("_", " "), lever.unit)


def format_lever_value(lever: LeverSpec, value: float) -> str:
    copy = _lever_copy(lever)
    whole = lever.step >= 1 or abs(value) >= 100
    number = f"{value:,.0f}" if whole else f"{value:,.4g}"
    if copy.currency:
        sign = "-" if value < 0 else ""
        magnitude = f"{abs(value):,.0f}" if whole else f"{abs(value):,.4g}"
        return f"{sign}${magnitude}{copy.unit_label}"
    return f"{number} {copy.unit_label}"


def _bare_value(lever: LeverSpec, value: float) -> str:
    """The number alone, for "from X to Y unit" phrasing."""
    copy = _lever_copy(lever)
    text = format_lever_value(lever, value)
    return text.removesuffix(copy.unit_label).strip() if copy.unit_label else text


def _pct(probability: float) -> str:
    return f"{probability * 100:.0f}%"


def _pp(delta: float) -> str:
    return f"{abs(delta) * 100:.0f} pp"


def range_used(lever: LeverSpec, value: float) -> float:
    bound = lever.maximum if lever.increasing else lever.minimum
    room = abs(bound - lever.baseline)
    if room <= 0:
        return 0.0
    return min(1.0, abs(value - lever.baseline) / room)


def relative_change(lever: LeverSpec, value: float) -> float | None:
    if abs(lever.baseline) < lever.step:
        return None
    return (value - lever.baseline) / abs(lever.baseline)


def classify_effort(lever: LeverSpec, value: float) -> EffortLevel:
    if abs(value - lever.baseline) < lever.step / 2:
        return "none"
    used = range_used(lever, value)
    if used >= EFFORT_HEAVY_RANGE:
        return "heavy"
    ratio = relative_change(lever, value)
    if ratio is not None:
        magnitude = abs(ratio)
        if magnitude <= EFFORT_LIGHT_MAX_RATIO:
            return "light"
        if magnitude <= EFFORT_MODERATE_MAX_RATIO:
            return "moderate"
        return "heavy"
    if used <= EFFORT_LIGHT_MAX_RANGE:
        return "light"
    if used <= EFFORT_MODERATE_MAX_RANGE:
        return "moderate"
    return "heavy"


def lever_change(setting: LeverSetting) -> BlueprintLeverChange:
    lever, value = setting.lever, setting.value
    copy = _lever_copy(lever)
    delta = value - lever.baseline
    verb = "Raise" if delta > 0 else "Lower" if delta < 0 else "Keep"
    ratio = relative_change(lever, value)
    detail = f"{'+' if delta >= 0 else '-'}{format_lever_value(lever, abs(delta))}"
    if ratio is not None and delta != 0 and lever.baseline > 0:
        detail += f", {value / lever.baseline:.1f}× today"
    if verb == "Keep":
        description = f"Keep {copy.noun} at {format_lever_value(lever, value)}"
    else:
        description = (
            f"{verb} {copy.noun} from {_bare_value(lever, lever.baseline)} "
            f"to {format_lever_value(lever, value)} ({detail})"
        )
    return BlueprintLeverChange(
        lever_id=lever.lever_id,
        label=copy.noun[:1].upper() + copy.noun[1:],
        unit=lever.unit,
        baseline_value=lever.baseline,
        recommended_value=value,
        change=delta,
        relative_change=ratio,
        range_used=range_used(lever, value),
        effort=classify_effort(lever, value),
        description=description,
    )


def effort_score(option: PricedOption) -> float:
    score = 0.0
    for setting in option.settings:
        ratio = relative_change(setting.lever, setting.value)
        score += abs(ratio) if ratio is not None else range_used(setting.lever, setting.value)
    for action in option.actions:
        score += action.hours_per_week / ACTION_HOURS_PER_EFFORT_UNIT
        score += action.money / ACTION_MONEY_PER_EFFORT_UNIT
    return score


def option_label(option: PricedOption) -> str:
    parts = [
        f"{_lever_copy(s.lever).noun} at {format_lever_value(s.lever, s.value)}"
        for s in option.settings
    ]
    parts.extend(action.title for action in option.actions)
    if not parts:
        return "No change"
    text = " + ".join(parts)
    return text[:1].upper() + text[1:]


def efficient_options(
    options: Sequence[PricedOption],
    baseline: float,
    tolerance: float = DEDUPE_TOLERANCE,
    *,
    reaches: Callable[[float], bool] | None = None,
) -> list[PricedOption]:
    """Cheapest-first frontier: each kept option must beat every cheaper kept one.

    Options that do not move the odds past baseline, or that cost more for odds
    within `tolerance` of a cheaper option, are dropped. The one exception is the
    first option that `reaches` the target: it is kept even when it is within
    `tolerance` of a cheaper option that does not. The result is strictly increasing
    in both effort and modeled odds.
    """

    ordered = sorted(options, key=lambda item: (effort_score(item), -item.probability, item.id))
    kept: list[PricedOption] = []
    best = baseline
    reached = False
    for option in ordered:
        crosses = reaches is not None and not reached and reaches(option.probability)
        if option.probability <= best + tolerance and not crosses:
            continue
        if option.probability <= best:
            continue
        kept.append(option)
        best = option.probability
        reached = reached or crosses
    return kept


def detect_plateau(
    scan: LeverScan,
    *,
    baseline: float,
    follow_through: float | None,
    gain_tolerance: float = PLATEAU_GAIN_TOLERANCE,
) -> BlueprintPlateau | None:
    """Find where the rest of a lever's range adds less than `gain_tolerance`."""

    lever = scan.lever
    points = sorted(scan.points, key=lambda p: p.value, reverse=not lever.increasing)
    if len(points) < 2:
        return None
    best = max(point.probability for point in points)
    start_index = next(
        index for index, point in enumerate(points) if best - point.probability <= gain_tolerance
    )
    if start_index >= len(points) - 1:
        return None
    start = points[start_index]
    copy = _lever_copy(lever)
    ceiling = (
        baseline + follow_through * (1 - baseline)
        if follow_through is not None and follow_through < 1
        else None
    )
    capped_by_follow_through = ceiling is not None and (
        ceiling - best <= FOLLOW_THROUGH_CAP_MARGIN
        or (start.conditional is not None and start.conditional >= SATURATED_CONDITIONAL)
    )
    where = format_lever_value(lever, start.value)
    if capped_by_follow_through:
        assert follow_through is not None
        modeled = f"follow-through is modeled at {_pct(follow_through)}"
        why = (
            f"With full follow-through the model reaches {_pct(start.conditional)}, "
            f"but {modeled}"
            if start.conditional is not None
            else modeled[:1].upper() + modeled[1:]
        )
        explanation = (
            f"Odds level off near {_pct(best)} from about {where}. {why}: in futures "
            f"where the plan slips, the change does nothing. More {copy.noun} past "
            f"{where} adds under {_pp(gain_tolerance)}."
        )
        cause = "follow_through"
    else:
        explanation = (
            f"Odds level off near {_pct(best)} from about {where}: the model's response "
            f"to {copy.noun} saturates before the deadline, so more past {where} adds "
            f"under {_pp(gain_tolerance)}."
        )
        cause = "saturation"
    return BlueprintPlateau(
        lever_id=lever.lever_id,
        plateau_probability=best,
        starts_at_value=start.value,
        cause=cause,
        explanation=explanation,
    )


def _range_limit(scan: LeverScan, target: float) -> BlueprintPlateau:
    lever = scan.lever
    best = max(point.probability for point in scan.points)
    bound = lever.maximum if lever.increasing else lever.minimum
    copy = _lever_copy(lever)
    return BlueprintPlateau(
        lever_id=lever.lever_id,
        plateau_probability=best,
        starts_at_value=bound,
        cause="lever_range",
        explanation=(
            f"Odds are still rising at {format_lever_value(lever, bound)}, the edge of the "
            f"range the model allows for {copy.noun}; {_pct(target)} would need more than "
            "that range."
        ),
    )


def _short_change(change: BlueprintLeverChange, lever: LeverSpec) -> str:
    verb = "raise" if change.change > 0 else "lower"
    where = format_lever_value(lever, change.recommended_value)
    return f"{verb} {_lever_copy(lever).noun} to {where}"


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _steps(
    option: PricedOption, changes: list[BlueprintLeverChange], follow_through: float | None
) -> list[str]:
    steps = [f"{change.description}." for change in changes]
    for action in option.actions:
        hours = f" (about {action.hours_per_week:g} h/week)" if action.hours_per_week else ""
        steps.append(f"Add {action.title}{hours}.")
    if follow_through is not None and follow_through < 1 and (changes or option.actions):
        steps.append(
            f"Stick with it: these odds assume the change holds in about "
            f"{_pct(follow_through)} of futures, so slipping more lowers them."
        )
    steps.append("Hold everything else at today's evidence, and log progress so the odds re-price.")
    return steps


def _tradeoffs(
    option: PricedOption,
    changes: list[BlueprintLeverChange],
    frontier: list[PricedOption],
    target: float,
    tolerance: float,
) -> list[str]:
    notes: list[str] = []
    for change in changes:
        where = format_lever_value(
            next(s.lever for s in option.settings if s.lever.lever_id == change.lever_id),
            change.recommended_value,
        )
        if change.effort == "heavy":
            notes.append(f"{change.label} at {where} is a heavy lift; check it fits your week.")
        elif change.effort == "moderate":
            notes.append(f"{change.label} at {where} is a moderate step up from today.")
        if change.range_used >= NEAR_BOUND_RANGE:
            notes.append(
                f"{where} is near the top of the range the model allows for "
                f"{change.label.lower()}; odds there are the least tested."
            )
    for action in option.actions:
        if action.hours_per_week or action.money:
            cost = ", ".join(
                part
                for part in (
                    f"{action.hours_per_week:g} h/week" if action.hours_per_week else "",
                    f"{action.money:,.0f} money" if action.money else "",
                )
                if part
            )
            notes.append(f"{action.title} costs {cost}.")
    cheaper = [
        item
        for item in frontier
        if effort_score(item) < effort_score(option)
        and item.probability + tolerance < target
    ]
    if cheaper:
        closest = max(cheaper, key=lambda item: item.probability)
        notes.append(
            f"A smaller change ({option_label(closest).lower()}) models "
            f"{_pct(closest.probability)}, {_pp(target - closest.probability)} short of target."
        )
    return notes


def _alternative(
    option: PricedOption, target: float, tolerance: float, recommended: PricedOption
) -> BlueprintAlternative:
    reaches = option.probability + tolerance >= target
    cheaper = effort_score(option) < effort_score(recommended)
    if reaches and not cheaper:
        note = "Also reaches the target, with a larger change."
    elif reaches:
        note = "Reaches the target."
    elif cheaper:
        note = f"Smaller change, {_pp(target - option.probability)} short of target."
    else:
        note = f"Larger change, still {_pp(target - option.probability)} short of target."
    return BlueprintAlternative(
        id=option.id,
        label=option_label(option),
        lever_changes=[lever_change(setting) for setting in option.settings],
        actions=list(option.actions),
        modeled_probability=option.probability,
        reaches_target=reaches,
        effort_score=round(effort_score(option), 4),
        note=note,
    )


def _plateau_for(
    inputs: BlueprintInputs, lever_ids: set[str], reachable: bool
) -> BlueprintPlateau | None:
    scans = [scan for scan in inputs.scans if scan.points]
    relevant = [scan for scan in scans if scan.lever.lever_id in lever_ids] or scans
    for scan in relevant:
        plateau = detect_plateau(
            scan, baseline=inputs.baseline, follow_through=inputs.follow_through
        )
        if plateau is not None:
            return plateau
    if not reachable and relevant:
        strongest = max(relevant, key=lambda s: max(p.probability for p in s.points))
        return _range_limit(strongest, inputs.target)
    return None


def build_reverse_blueprint(inputs: BlueprintInputs) -> ReverseBlueprint:
    target, baseline, tolerance = inputs.target, inputs.baseline, inputs.tolerance
    tolerance_pp = tolerance * 100
    if baseline + tolerance >= target:
        keep = [
            lever_change(LeverSetting(lever, lever.baseline)) for lever in inputs.levers
        ]
        return ReverseBlueprint(
            target_probability=target,
            baseline_probability=baseline,
            modeled_probability=baseline,
            delta_pp=0.0,
            reachable=True,
            already_satisfied=True,
            headline=(
                f"You're already at about {_pct(baseline)}, at or above the {_pct(target)} "
                "target. Keep the current plan."
            ),
            rationale="Today's evidence already clears the target; no change is needed.",
            lever_changes=keep,
            steps=[f"{change.description}." for change in keep]
            + ["Hold everything else at today's evidence, and log progress so the odds re-price."],
            follow_through_probability=inputs.follow_through,
            max_modeled_probability=baseline,
            tolerance_pp=tolerance_pp,
        )

    def reaches(probability: float) -> bool:
        return probability + tolerance >= target

    frontier = efficient_options(inputs.options, baseline, reaches=reaches)
    if not frontier:
        plateau = _plateau_for(inputs, {lever.lever_id for lever in inputs.levers}, False)
        return ReverseBlueprint(
            target_probability=target,
            baseline_probability=baseline,
            reachable=False,
            headline=(
                f"No modeled change moves the odds above about {_pct(baseline)}, so "
                f"{_pct(target)} is out of reach with these levers."
            ),
            rationale=(
                f"All {len(inputs.options)} priced options stayed within "
                f"{_pp(DEDUPE_TOLERANCE)} of today's odds."
                if inputs.options
                else "No supported lever could be priced for this goal."
            ),
            follow_through_probability=inputs.follow_through,
            max_modeled_probability=max(
                (item.probability for item in inputs.options), default=baseline
            ),
            plateau=plateau,
            tolerance_pp=tolerance_pp,
        )

    reaching = [item for item in frontier if reaches(item.probability)]
    reachable = bool(reaching)
    if reaching:
        chosen = reaching[0]
    else:
        # Past the cheapest option within a plateau's width of the best, effort buys nothing.
        top = frontier[-1].probability
        chosen = next(item for item in frontier if top - item.probability <= PLATEAU_GAIN_TOLERANCE)
    changes = [lever_change(setting) for setting in chosen.settings]
    lever_by_id = {setting.lever.lever_id: setting.lever for setting in chosen.settings}
    summary = [_short_change(change, lever_by_id[change.lever_id]) for change in changes]
    summary.extend(f"add {action.title}" for action in chosen.actions)
    plan = _join(summary)
    modeled = chosen.probability
    if reachable:
        headline = f"To reach ~{_pct(target)}: {plan}. Modeled odds {_pct(modeled)}."
        rationale = (
            f"The smallest change among {len(inputs.options)} priced options that reaches "
            f"{_pct(target)} (within {tolerance_pp:g} pp). Smaller and larger options are "
            "listed as alternatives."
        )
    else:
        headline = (
            f"{_pct(target)} is out of reach with these levers. Closest path: {plan}, "
            f"modeled at {_pct(modeled)}."
        )
        rationale = (
            f"No tested combination reaches {_pct(target)}. This is the highest modeled "
            f"result among {len(inputs.options)} priced options; past it, extra effort "
            "stops buying odds."
        )
    alternatives = [
        _alternative(item, target, tolerance, chosen) for item in frontier if item is not chosen
    ]
    alternatives.sort(key=lambda item: item.effort_score)
    return ReverseBlueprint(
        target_probability=target,
        baseline_probability=baseline,
        modeled_probability=modeled,
        delta_pp=(modeled - baseline) * 100,
        reachable=reachable,
        headline=headline,
        rationale=rationale,
        lever_changes=changes,
        actions=list(chosen.actions),
        steps=_steps(chosen, changes, inputs.follow_through),
        tradeoffs=_tradeoffs(chosen, changes, frontier, target, tolerance),
        follow_through_probability=inputs.follow_through,
        max_modeled_probability=max(item.probability for item in frontier),
        plateau=_plateau_for(inputs, set(lever_by_id), reachable),
        alternatives=alternatives[:MAX_ALTERNATIVES],
        tolerance_pp=tolerance_pp,
    )
