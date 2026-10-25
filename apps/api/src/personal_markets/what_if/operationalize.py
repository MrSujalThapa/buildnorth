# ruff: noqa: E501
"""Turn a strategy-style What If into measurable levers the engine already prices.

Pure and deterministic: no inference call and no probability. A strategy maps onto an
editable baseline assumption only through an explicit, documented mapping; when the
question has no quantity, the plan asks for one instead of assuming an effect size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from personal_markets.what_if.domain import Assumption, WhatIfBaselineState
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.strategy_plan import (
    StrategyAnalysisPoint,
    StrategyLever,
    StrategyPlan,
)

# Unit conversions for quantities stated per day or per month (calendar averages).
DAYS_PER_WEEK = 7.0
WEEKS_PER_MONTH = 52.0 / 12.0
# Suggested step sizes, as fractions of the current baseline value. Baselines below
# the threshold use the absolute steps instead, so suggestions stay meaningful.
SUGGESTED_FRACTIONS = (0.25, 0.5, 1.0)
SMALL_BASELINE_THRESHOLD = 8.0
SMALL_BASELINE_SUGGESTIONS = (2.0, 5.0, 10.0)


@dataclass(frozen=True, slots=True)
class _Family:
    id: str
    pattern: re.Pattern[str]
    targets: tuple[str, ...]
    interpretation: str
    unit_label: str
    question: str
    mapping_note: str
    analysis: tuple[tuple[str, str], ...]
    period: str = "week"


_FAMILIES: tuple[_Family, ...] = (
    _Family(
        id="outreach",
        pattern=re.compile(
            r"cold[\s-]?e?-?mail|\bemail(?:ing)?\b|outreach|reach(?:ing)? out|\bdms?\b|"
            r"\bmessag|network(?:ing)?|referr|recruiters?|coffee chats?|warm intros?|"
            r"connect(?:ing)? with|linkedin|hiring managers?",
            re.I,
        ),
        targets=("weekly_application_rate",),
        interpretation="direct outreach to people at companies you want to join",
        unit_label="targeted outreach emails per week",
        question="How many targeted cold emails will you send per week, on top of your current applications?",
        mapping_note=(
            "Modeled as extra entries in your weekly application pipeline: one targeted email to "
            "someone at a company you would join counts as one application. The model does not "
            "assume outreach converts better than an application."
        ),
        analysis=(
            (
                "How it can move your odds",
                "Outreach widens the top of your pipeline. The model credits it only through "
                "volume; reply and referral rates are not assumed.",
            ),
            (
                "What makes it count",
                "Write to named engineers or founders about a specific role, then log sends and "
                "replies as evidence so later forecasts use your real reply rate.",
            ),
            (
                "Tradeoff",
                "Generic bulk email adds volume without interviews and costs time you could spend "
                "on preparation. Keep each message specific.",
            ),
        ),
    ),
    _Family(
        id="applications",
        pattern=re.compile(r"\bappl(?:y|ying|ications?)\b|\bjob boards?\b", re.I),
        targets=("weekly_application_rate",),
        interpretation="sending more applications",
        unit_label="applications per week",
        question="How many more applications per week would you send?",
        mapping_note="Changes the weekly application rate the hiring model simulates.",
        analysis=(
            (
                "How it can move your odds",
                "More applications mean more chances at each interview stage at your observed "
                "pass rates.",
            ),
            ("Tradeoff", "Volume beyond what you can prepare for tends to lower stage pass rates."),
        ),
    ),
    _Family(
        id="savings",
        pattern=re.compile(
            r"\bsav(?:e|ing)\b|cut (?:back|spending|costs)|budget|side (?:hustle|income|gig)|"
            r"\binvest|contribut|raise|bonus|spend less",
            re.I,
        ),
        targets=("flow",),
        interpretation="putting more money toward the goal each month",
        unit_label="extra dollars per month",
        question="How much more per month could you put toward this goal?",
        mapping_note="Adds to the monthly contribution the finance model simulates.",
        analysis=(
            (
                "How it can move your odds",
                "A higher monthly contribution compounds over the remaining months before the "
                "deadline.",
            ),
            ("Tradeoff", "Only count money you can sustain every month, not a one-off."),
        ),
        period="month",
    ),
    _Family(
        id="cadence",
        pattern=re.compile(
            r"\b(?:more|extra|another|additional|daily|every day|each week|twice|again|"
            r"host|read|ship|log|practice|train|run|study|finish|complete|write|meditate)\b",
            re.I,
        ),
        targets=(".rate", "flow"),
        interpretation="doing the tracked activity more often",
        unit_label="extra per week",
        question="How many more per week would you realistically add?",
        mapping_note="Changes the weekly rate the progress model simulates for this goal.",
        analysis=(
            (
                "How it can move your odds",
                "A higher sustained rate moves the projected finish closer to the target before "
                "the deadline.",
            ),
            ("Tradeoff", "Pick a rate you can keep for the whole period; the model assumes it holds."),
        ),
    ),
)

_MONEY_UNITS = ("currency", "$", "usd", "cad", "dollar")


def _is_money(assumption: Assumption) -> bool:
    return any(token in assumption.unit.lower() for token in _MONEY_UNITS)


def _addable(assumption: Assumption, family: _Family) -> bool:
    # Pace-style flows (seconds/week, negative is faster) cannot take a positive "more".
    if assumption.unit.lower().startswith("second"):
        return False
    if family.id == "savings":
        return _is_money(assumption)
    return not (family.id == "cadence" and _is_money(assumption))


def _target(baseline: WhatIfBaselineState, family: _Family) -> Assumption | None:
    editable = [item for item in baseline.assumptions if item.editable]
    for target in family.targets:
        for item in editable:
            named = (target.startswith(".") and item.name.endswith(target)) or item.name == target
            if named and _addable(item, family):
                return item
    return None


def _lever_label(assumption: Assumption) -> str:
    if assumption.name == "weekly_application_rate":
        return "weekly applications"
    if assumption.name == "flow":
        return "monthly contribution" if _is_money(assumption) else "weekly progress rate"
    if assumption.name.endswith(".rate"):
        return f"{assumption.name.split('.')[0].replace('_', ' ')} rate"
    return assumption.name.replace("_", " ")


_PERIOD_AFTER = re.compile(
    r"\b(?:per|a|an|each|every|/)\s*(day|week|wk|month|mo)\b|\b(daily|weekly|monthly)\b", re.I
)


def _stated_quantity(text: str, period: str) -> float | None:
    number = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)", text)
    if number is None:
        return None
    value = float(number.group(1).replace(",", ""))
    unit = _PERIOD_AFTER.search(text, number.end())
    stated = (unit.group(1) or unit.group(2)) if unit else None
    return _per_period(value, stated, period)


def _per_period(value: float, stated: str | None, period: str) -> float:
    unit = (stated or period).lower()
    if unit == period or (unit.startswith("m") and period == "month"):
        return value
    if unit.startswith("d"):
        per_week = value * DAYS_PER_WEEK
    elif unit.startswith("m"):
        per_week = value / WEEKS_PER_MONTH
    else:
        per_week = value
    return per_week * WEEKS_PER_MONTH if period == "month" else per_week


def _suggestions(assumption: Assumption) -> list[float]:
    base = abs(assumption.value)
    raw = (
        [base * fraction for fraction in SUGGESTED_FRACTIONS]
        if base >= SMALL_BASELINE_THRESHOLD
        else list(SMALL_BASELINE_SUGGESTIONS)
    )
    step = assumption.step or 1.0
    values: list[float] = []
    for item in raw:
        rounded = max(step, round(item / step) * step)
        if rounded not in values and assumption.value + rounded <= assumption.maximum:
            values.append(round(rounded, 4))
    return values


def operationalize_strategy(
    baseline: WhatIfBaselineState, text: str
) -> tuple[StrategyPlan, list[InterventionChangeResponse]] | None:
    """Map a strategy onto a priced lever; return the plan and any stated change."""
    if not baseline.priced or not text.strip():
        return None
    for family in _FAMILIES:
        if not family.pattern.search(text):
            continue
        assumption = _target(baseline, family)
        if assumption is None:
            continue
        lever = StrategyLever(
            assumption=assumption.name,
            label=_lever_label(assumption),
            unit=assumption.unit,
            unit_label=family.unit_label,
            baseline_value=assumption.value,
            minimum=assumption.minimum,
            maximum=assumption.maximum,
            question=family.question,
            mapping_note=family.mapping_note,
            suggested_values=_suggestions(assumption),
        )
        quantity = _stated_quantity(text, family.period)
        changes = (
            [
                InterventionChangeResponse(
                    metric=assumption.name,
                    operation="add",
                    value=round(quantity, 4),
                    unit=assumption.unit,
                    frequency=family.period,
                    provenance="USER_ASSUMPTION",
                )
            ]
            if quantity is not None and quantity > 0
            else []
        )
        plan = StrategyPlan(
            family=family.id,
            interpretation=(
                f"You are considering {family.interpretation}. PlayItOut can price that through "
                f"one modeled lever: {lever.label} (currently {assumption.value:g} {assumption.unit})."
            ),
            levers=[lever],
            needs=[] if changes else [family.question],
            analysis=[StrategyAnalysisPoint(heading=h, body=b) for h, b in family.analysis],
            stated_quantity=round(quantity, 4) if changes and quantity is not None else None,
            modeled=bool(changes),
        )
        return plan, changes
    return None


def plan_summary(plan: StrategyPlan) -> str:
    lever = plan.levers[0]
    if plan.modeled and plan.stated_quantity is not None:
        return (
            f"Read as +{plan.stated_quantity:g} {lever.unit_label} through {lever.label}. "
            "The result below is the engine's modeled scenario, not a new published forecast."
        )
    examples = ", ".join(f"+{value:g}" for value in lever.suggested_values[:3])
    return (
        f"{plan.interpretation} To run it, say how much: {lever.question}"
        + (f" For example {examples} {lever.unit_label}." if examples else "")
        + " No probability change is assumed until you give a number."
    )
