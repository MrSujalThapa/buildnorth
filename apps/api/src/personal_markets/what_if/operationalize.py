# ruff: noqa: E501
"""Turn a strategy-style What If into measurable levers the engine already prices.

Pure and deterministic: no inference call and no probability. A strategy maps onto an
editable baseline assumption only through an explicit option the user chooses; when an
effect size is unknown (for example the reply rate of cold email) the user supplies it
as a labeled assumption, or the plan stays qualitative with metrics to track.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from personal_markets.what_if.domain import Assumption, WhatIfBaselineState
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.strategy_plan import (
    StrategyAnalysisPoint,
    StrategyChangesResponse,
    StrategyInput,
    StrategyLever,
    StrategyOption,
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
# Example reply rates offered as quick picks. They are prompts for the user's own
# estimate, never applied without the user choosing one.
REPLY_RATE_EXAMPLES = (5.0, 10.0, 20.0)
PERCENT = 100.0

OPTION_DIRECT = "direct"
OPTION_PROXY = "as_applications"
OPTION_REPLY_RATE = "reply_rate"
INPUT_AMOUNT = "amount"
INPUT_REPLY_RATE = "reply_rate_pct"
INPUT_HOURS = "hours_per_week"

RESPONSE_STAGE = "application_to_response"
APPLICATION_RATE = "weekly_application_rate"


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
    outcomes: tuple[str, ...]
    metrics: tuple[str, ...]
    period: str = "week"
    # Without a lever on this goal, still answer qualitatively instead of falling through.
    qualitative_fallback: bool = True


_FAMILIES: tuple[_Family, ...] = (
    _Family(
        id="outreach",
        pattern=re.compile(
            r"cold[\s-]?e?-?mail|\bemail(?:ing)?\b|outreach|reach(?:ing)? out|\bdms?\b|"
            r"\bmessag|network(?:ing)?|referr|recruiters?|coffee chats?|warm intros?|"
            r"connect(?:ing)? with|linkedin|hiring managers?",
            re.I,
        ),
        targets=(APPLICATION_RATE,),
        interpretation="direct outreach to people at companies you want to join",
        unit_label="outreach emails per week",
        question="How many targeted cold emails will you send per week?",
        mapping_note=(
            "A cold email is not an application. It can earn a reply, a referral or an "
            "introduction, which then enters the same screen-to-offer stages."
        ),
        analysis=(
            (
                "How it can move your odds",
                "Outreach adds conversations at the top of your pipeline. Its value depends on "
                "the reply rate, which the model has not observed for you yet.",
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
        outcomes=(
            "Replies from people you contact",
            "Referrals and warm introductions",
            "Recruiter and phone screens",
            "Pipeline size",
            "Offers",
        ),
        metrics=(
            "Outreach emails sent per week",
            "Replies received",
            "Referrals or intros from replies",
            "Screens that started from outreach",
        ),
    ),
    _Family(
        id="applications",
        pattern=re.compile(r"\bappl(?:y|ying|ications?)\b|\bjob boards?\b", re.I),
        targets=(APPLICATION_RATE,),
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
        outcomes=("Responses", "Phone screens", "Interviews", "Offers"),
        metrics=("Applications submitted per week", "Responses received"),
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
        outcomes=("Monthly contribution", "Balance at the deadline"),
        metrics=("Amount moved toward the goal each month", "Account balance"),
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
        mapping_note="Changes the rate the progress model simulates for this goal.",
        analysis=(
            (
                "How it can move your odds",
                "A higher sustained rate moves the projected finish closer to the target before "
                "the deadline.",
            ),
            ("Tradeoff", "Pick a rate you can keep for the whole period; the model assumes it holds."),
        ),
        outcomes=("Progress per week", "Projected total at the deadline"),
        metrics=("Completed units per week",),
        qualitative_fallback=False,
    ),
)

_MONEY_UNITS = ("currency", "$", "usd", "cad", "dollar")
_DECREASE = re.compile(r"\b(?:stop|pause|quit|skip|fewer|reduce|less|lower|drop)\b", re.I)
# Phrases where "less" describes spending, which raises savings rather than lowering it.
_SPEND_LESS = re.compile(r"spend(?:ing)?\s+less|less\s+spending|cut (?:back|spending|costs)", re.I)
_TEMPORARY = re.compile(r"\bfor\s+(?:the\s+next\s+)?\d+\s*(?:day|week|month)s?\b", re.I)


def is_decrease(text: str) -> bool:
    return bool(_DECREASE.search(text)) and not _SPEND_LESS.search(text)
_PROXY_ACCEPTED = re.compile(
    r"\b(?:as|like|count(?:ed|s|ing)?\s+(?:them\s+)?as|treat(?:ed|ing)?\s+(?:them\s+)?as)\s+"
    r"(?:an?\s+)?(?:job\s+)?applications?\b",
    re.I,
)
_REPLY_RATE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:reply|response)|(?:reply|response)\s+rate\s+(?:of\s+|at\s+|is\s+)?(\d+(?:\.\d+)?)\s*%",
    re.I,
)


def _is_money(assumption: Assumption) -> bool:
    return any(token in assumption.unit.lower() for token in _MONEY_UNITS)


def _addable(assumption: Assumption, family: _Family) -> bool:
    # Pace-style flows (seconds/week, negative is faster) cannot take a positive "more".
    if assumption.unit.lower().startswith("second"):
        return False
    if family.id == "savings":
        return _is_money(assumption)
    return not (family.id == "cadence" and _is_money(assumption))


def _editable(baseline: WhatIfBaselineState, name: str) -> Assumption | None:
    return next(
        (item for item in baseline.assumptions if item.editable and item.name == name), None
    )


def _target(baseline: WhatIfBaselineState, family: _Family) -> Assumption | None:
    editable = [item for item in baseline.assumptions if item.editable]
    for target in family.targets:
        for item in editable:
            named = (target.startswith(".") and item.name.endswith(target)) or item.name == target
            if named and _addable(item, family):
                return item
    return None


def _unit_period(assumption: Assumption, fallback: str) -> str:
    suffix = assumption.unit.rsplit("/", 1)[-1].strip().lower() if "/" in assumption.unit else ""
    return suffix if suffix in {"day", "week", "month"} else fallback


def _unit_noun(assumption: Assumption) -> str:
    noun = assumption.unit.split("/", 1)[0].replace("_", " ").strip()
    return re.sub(r"\s+count$", "", noun) or "units"


def _lever_label(assumption: Assumption, period: str) -> str:
    if assumption.name == APPLICATION_RATE:
        return "weekly applications"
    if assumption.name == "flow":
        return "monthly contribution" if _is_money(assumption) else "weekly progress rate"
    if assumption.name.endswith(".rate"):
        return f"{_unit_noun(assumption)} per {period}"
    return assumption.name.replace("_", " ")


def _family_unit_label(family: _Family, assumption: Assumption, period: str) -> str:
    if family.id == "cadence" and assumption.name.endswith(".rate"):
        return f"more {_unit_noun(assumption)} per {period}"
    return family.unit_label


_PERIOD_AFTER = re.compile(
    r"\b(?:per|a|an|each|every|/)\s*(day|week|wk|month|mo)\b|\b(daily|weekly|monthly)\b", re.I
)


def _stated_quantity(text: str, period: str) -> float | None:
    cleaned = _REPLY_RATE.sub(" ", text)
    number = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)(?!\s*%)", cleaned)
    if number is None:
        return None
    value = float(number.group(1).replace(",", ""))
    unit = _PERIOD_AFTER.search(cleaned, number.end())
    stated = (unit.group(1) or unit.group(2)) if unit else None
    return _per_period(value, stated, period)


def _stated_reply_rate(text: str) -> float | None:
    match = _REPLY_RATE.search(text)
    if match is None:
        return None
    value = float(match.group(1) or match.group(2))
    return value if 0 < value <= PERCENT else None


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


def _room(assumption: Assumption, decrease: bool) -> float:
    return assumption.value - assumption.minimum if decrease else assumption.maximum - assumption.value


def _suggestions(assumption: Assumption, decrease: bool = False) -> list[float]:
    base = abs(assumption.value)
    raw = (
        [base * fraction for fraction in SUGGESTED_FRACTIONS]
        if base >= SMALL_BASELINE_THRESHOLD or decrease
        else list(SMALL_BASELINE_SUGGESTIONS)
    )
    step = assumption.step if assumption.step and assumption.step >= 1 else None
    room = _room(assumption, decrease)
    values: list[float] = []
    for item in raw:
        rounded = max(step, round(item / step) * step) if step else round(item, 2)
        if rounded > 0 and rounded not in values and rounded <= room:
            values.append(round(rounded, 4))
    return values


def _hours_input() -> StrategyInput:
    return StrategyInput(
        key=INPUT_HOURS,
        label="Time this takes each week (optional)",
        unit="hours/week",
        minimum=0.0,
        required=False,
    )


def _amount_input(family: _Family, lever: StrategyLever, quantity: float | None) -> StrategyInput:
    decrease = lever.operation == "subtract"
    bound = lever.minimum if decrease else lever.maximum
    headroom = (
        abs(lever.baseline_value - bound)
        if bound is not None and lever.baseline_value is not None
        else None
    )
    return StrategyInput(
        key=INPUT_AMOUNT,
        label=lever.question,
        unit=lever.unit_label,
        minimum=0.0,
        maximum=headroom,
        value=quantity,
        suggested_values=lever.suggested_values,
    )


def _options(
    family: _Family, baseline: WhatIfBaselineState, lever: StrategyLever, quantity: float | None, text: str
) -> list[StrategyOption]:
    amount = _amount_input(family, lever, quantity)
    if family.id != "outreach":
        return [
            StrategyOption(
                id=OPTION_DIRECT,
                label=f"Change {lever.label}",
                description=lever.mapping_note,
                inputs=[amount, _hours_input()],
            )
        ]
    response = _editable(baseline, RESPONSE_STAGE)
    options = [
        StrategyOption(
            id=OPTION_PROXY,
            label="Count each email as one application",
            description=(
                "A simplifying proxy: every email is treated like an application at your "
                "current application-to-response rate"
                + (f" ({response.value * PERCENT:.0f}%)" if response is not None else "")
                + ". Use it only if you think a cold email performs like an application."
            ),
            proxy=True,
            inputs=[amount, _hours_input()],
        )
    ]
    if response is not None:
        options.insert(
            0,
            StrategyOption(
                id=OPTION_REPLY_RATE,
                label="Use my expected reply rate",
                description=(
                    "Emails enter the pipeline at the reply rate you expect. A reply is "
                    "treated as a response that then goes through your screen-to-offer "
                    "stages. The rate is your assumption until you log real replies."
                ),
                inputs=[
                    amount,
                    StrategyInput(
                        key=INPUT_REPLY_RATE,
                        label="What share of emails do you expect to get a reply?",
                        unit="% replies",
                        minimum=0.0,
                        maximum=PERCENT,
                        value=_stated_reply_rate(text),
                        suggested_values=list(REPLY_RATE_EXAMPLES),
                    ),
                    _hours_input(),
                ],
            ),
        )
    return options


def _selected_option(family: _Family, text: str, options: list[StrategyOption]) -> str | None:
    ids = {item.id for item in options}
    if family.id != "outreach":
        return OPTION_DIRECT
    if OPTION_REPLY_RATE in ids and _stated_reply_rate(text) is not None:
        return OPTION_REPLY_RATE
    if _PROXY_ACCEPTED.search(text):
        return OPTION_PROXY
    return None


def _qualitative_plan(family: _Family, baseline: WhatIfBaselineState) -> StrategyPlan:
    return StrategyPlan(
        family=family.id,
        interpretation=(
            f"You are considering {family.interpretation}. This goal's model has no input "
            "that this action changes, so PlayItOut will not put a number on it."
        ),
        levers=[],
        needs=[],
        analysis=[StrategyAnalysisPoint(heading=h, body=b) for h, b in family.analysis],
        affected_outcomes=list(family.outcomes),
        metrics_to_track=list(family.metrics),
        unpriced=True,
    )


def operationalize_strategy(
    baseline: WhatIfBaselineState, text: str
) -> tuple[StrategyPlan, list[InterventionChangeResponse]] | None:
    """Map a strategy onto priced options; return the plan and any change it fully specifies."""
    if not text.strip():
        return None
    for family in _FAMILIES:
        if not family.pattern.search(text):
            continue
        decrease = is_decrease(text)
        assumption = _target(baseline, family) if baseline.priced else None
        if assumption is None or (decrease and family.id == "outreach"):
            if family.qualitative_fallback and baseline.priced:
                return _qualitative_plan(family, baseline), []
            continue
        period = _unit_period(assumption, family.period)
        unit_label = _family_unit_label(family, assumption, period)
        label = _lever_label(assumption, period)
        question = (
            family.question
            if not (family.id == "cadence" and assumption.name.endswith(".rate"))
            else f"How many more {_unit_noun(assumption)} per {period} would you realistically add?"
        )
        lever = StrategyLever(
            assumption=assumption.name,
            label=label,
            unit=assumption.unit,
            unit_label=unit_label.replace("extra ", "").replace("more ", "fewer ")
            if decrease
            else unit_label,
            baseline_value=assumption.value,
            minimum=assumption.minimum,
            maximum=assumption.maximum,
            operation="subtract" if decrease else "add",
            question=f"By how much would {label} drop? ({assumption.unit})" if decrease else question,
            mapping_note=family.mapping_note,
            suggested_values=_suggestions(assumption, decrease),
        )
        quantity = _stated_quantity(text, period)
        options = _options(family, baseline, lever, quantity, text)
        selected = _selected_option(family, text, options)
        resolved = (
            resolve_option(baseline, family.id, selected, _stated_inputs(options, selected), text)
            if selected is not None and quantity is not None and quantity > 0
            else None
        )
        changes = (
            [InterventionChangeResponse.model_validate(item) for item in resolved.changes]
            if resolved is not None
            else []
        )
        needs: list[str] = []
        if selected is None:
            needs.append("Choose how to model it: your expected reply rate, or the application proxy.")
        if quantity is None or quantity <= 0:
            needs.append(lever.question)
        analysis = [StrategyAnalysisPoint(heading=h, body=b) for h, b in family.analysis]
        if decrease:
            analysis = [
                StrategyAnalysisPoint(
                    heading="How it can move your odds",
                    body=f"Lower {lever.label} means less progress each {period}; the model "
                    "prices the drop as a future assumption, not as something that happened.",
                )
            ]
        if _TEMPORARY.search(text):
            analysis.append(
                StrategyAnalysisPoint(
                    heading="Limitation",
                    body="The model applies the change until the deadline. It cannot yet price a "
                    "change that lasts only part of the period, so read this as the full-horizon case.",
                )
            )
        verb = "lowering" if decrease else "changing"
        interpretation = (
            f"You are considering {verb} {lever.label}. PlayItOut prices that directly "
            f"(currently {assumption.value:g} {assumption.unit})."
            if decrease
            else f"You are considering {family.interpretation}. PlayItOut can price it through "
            f"{lever.label} (currently {assumption.value:g} {assumption.unit})"
            + (" once you choose how replies are modeled." if family.id == "outreach" else ".")
        )
        plan = StrategyPlan(
            family=family.id,
            interpretation=interpretation,
            levers=[lever],
            needs=needs,
            analysis=analysis,
            stated_quantity=round(quantity, 4) if changes and quantity is not None else None,
            modeled=bool(changes),
            affected_outcomes=list(family.outcomes),
            options=options,
            selected_option=selected,
            metrics_to_track=list(family.metrics),
            conflicts=list(resolved.conflicts) if resolved is not None else [],
        )
        return plan, changes
    return None


def _stated_inputs(options: list[StrategyOption], selected: str | None) -> dict[str, float]:
    option = next((item for item in options if item.id == selected), None)
    if option is None:
        return {}
    return {item.key: item.value for item in option.inputs if item.value is not None}


def _family(family_id: str) -> _Family | None:
    return next((item for item in _FAMILIES if item.id == family_id), None)


def resolve_option(
    baseline: WhatIfBaselineState,
    family_id: str,
    option_id: str,
    inputs: dict[str, float],
    text: str = "",
) -> StrategyChangesResponse:
    """Build the model changes for a chosen option, or explain why they would be invalid."""
    family = _family(family_id)
    assumption = _target(baseline, family) if family is not None and baseline.priced else None
    title = text.strip() or (family.interpretation if family else "Strategy")
    if family is None or assumption is None:
        return StrategyChangesResponse(
            option_id=option_id,
            title=title,
            conflicts=["This goal's model has no input that this strategy changes."],
        )
    period = _unit_period(assumption, family.period)
    decrease = is_decrease(text)
    amount = float(inputs.get(INPUT_AMOUNT) or 0.0)
    conflicts: list[str] = []
    if amount <= 0:
        conflicts.append("Enter an amount above zero.")
    if amount > _room(assumption, decrease):
        resulting = assumption.value - amount if decrease else assumption.value + amount
        edge = assumption.minimum if decrease else assumption.maximum
        conflicts.append(
            f"{resulting:g} {assumption.unit} is outside the model's supported range "
            f"(limit {edge:g}). Pricing it would be extrapolation, so it was not run."
        )
    if baseline.periods is not None and baseline.periods < 1:
        conflicts.append("The deadline has passed, so there is no time left for this change.")
    hours = inputs.get(INPUT_HOURS)
    budget = baseline.resource_budget.hours_per_week if baseline.resource_budget else 0.0
    if hours is not None and budget and hours > budget:
        conflicts.append(
            f"This takes {hours:g} hours/week but the goal's time budget is {budget:g} hours/week. "
            "Raise the budget on the goal or plan less."
        )
    changes: list[InterventionChangeResponse] = []
    assumptions_used: list[str] = []
    proxy = False
    if option_id == OPTION_REPLY_RATE and family.id == "outreach":
        response = _editable(baseline, RESPONSE_STAGE)
        reply = inputs.get(INPUT_REPLY_RATE)
        if response is None:
            conflicts.append("This goal's model has no response-rate stage to apply a reply rate to.")
        elif reply is None or not 0 < reply <= PERCENT:
            conflicts.append("Enter the share of emails you expect to get a reply, between 0 and 100%.")
        elif not conflicts:
            current = max(assumption.value, 0.0)
            rate = reply / PERCENT
            blended = (current * response.value + amount * rate) / (current + amount)
            blended = min(max(blended, response.minimum), response.maximum)
            changes = [
                _change(assumption, "add", amount, period),
                _change(response, "set", round(blended, 4), None),
            ]
            assumptions_used = [
                f"Your assumption: {reply:g}% of cold emails get a reply.",
                f"Blended response rate {blended * PERCENT:.1f}% across {current:g} applications and "
                f"{amount:g} emails per week (applications keep {response.value * PERCENT:.1f}%).",
                "A reply is treated as a response; later stages keep their current rates.",
            ]
    elif option_id in {OPTION_PROXY, OPTION_DIRECT}:
        proxy = option_id == OPTION_PROXY
        if not conflicts:
            changes = [_change(assumption, "subtract" if decrease else "add", amount, period)]
            sign = "−" if decrease else "+"
            assumptions_used = (
                ["Proxy you chose: each cold email counts as one application."]
                if proxy
                else [f"Your assumption: {sign}{amount:g} {assumption.unit} sustained until the deadline."]
            )
    else:
        conflicts.append("Unknown option for this strategy.")
    return StrategyChangesResponse(
        option_id=option_id,
        title=title,
        changes=[item.model_dump(mode="json") for item in changes] if not conflicts else [],
        assumptions_used=assumptions_used if not conflicts else [],
        conflicts=conflicts,
        proxy=proxy,
    )


def _change(
    assumption: Assumption, operation: str, value: float, period: str | None
) -> InterventionChangeResponse:
    return InterventionChangeResponse(
        metric=assumption.name,
        operation=operation,
        value=round(value, 4),
        unit=assumption.unit,
        frequency=period,
        provenance="USER_ASSUMPTION",
    )


def plan_summary(plan: StrategyPlan) -> str:
    if plan.unpriced or not plan.levers:
        return (
            f"{plan.interpretation} Track the metrics below; once they are logged as evidence "
            "they can enter the forecast."
        )
    lever = plan.levers[0]
    if plan.conflicts:
        return f"{plan.interpretation} Not run: {plan.conflicts[0]}"
    if plan.modeled and plan.stated_quantity is not None:
        return (
            f"Read as {'−' if lever.operation == 'subtract' else '+'}{plan.stated_quantity:g} "
            f"{lever.unit_label} through {lever.label}. "
            "The result below is the engine's modeled scenario, not a new published forecast."
        )
    return (
        f"{plan.interpretation} {' '.join(plan.needs)}"
        + " No probability change is assumed until you give the missing inputs."
    )
