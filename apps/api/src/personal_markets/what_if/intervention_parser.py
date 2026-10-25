from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Operation = Literal["set", "add", "subtract"]


@dataclass(frozen=True, slots=True)
class TypedInterventionChange:
    metric: str
    operation: Operation
    value: float
    unit: str
    frequency: str | None = None
    scope: str = "goal_state"
    provenance: str = "USER_ASSUMPTION"


@dataclass(frozen=True, slots=True)
class ParsedIntervention:
    raw_text: str
    changes: tuple[TypedInterventionChange, ...]
    unsupported: tuple[str, ...]


_MONEY = re.compile(
    r"\$?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:/|\sper\s|\s*a\s*)?(month|week|day)?",
    re.IGNORECASE,
)
_WEEKLY_KM = re.compile(r"(\d+(?:\.\d+)?)\s*km\s*/?\s*week", re.IGNORECASE)
_DAILY_PROBLEMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:leetcode\s*)?(?:problems?|questions?)\s*(?:every\s*day|/day|per\s*day)",
    re.IGNORECASE,
)
_APPLICATIONS = re.compile(
    r"(\d+(?:\.\d+)?)\s*applications?\s*(?:/|\sper\s|\sa\s*)?(week|month)?",
    re.IGNORECASE,
)
_RUN_DAYS = re.compile(
    r"run\s*(\d+(?:\.\d+)?)\s*(?:days?|times?)\s*(?:/|\sper\s|\sa\s*)?week",
    re.IGNORECASE,
)
_BURN = re.compile(
    r"(?:burn|spend).*?\$?\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:/|\sper\s|\sa\s*)?(month|week)?",
    re.IGNORECASE,
)


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_intervention_text(text: str) -> ParsedIntervention:
    cleaned = text.strip()
    if not cleaned:
        return ParsedIntervention(raw_text=text, changes=(), unsupported=("empty input",))

    changes: list[TypedInterventionChange] = []
    unsupported: list[str] = []

    for match in _DAILY_PROBLEMS.finditer(cleaned):
        changes.append(
            TypedInterventionChange(
                metric="daily_practice_problems",
                operation="set",
                value=_parse_number(match.group(1)),
                unit="count/day",
                frequency="daily",
                provenance="USER_ASSUMPTION",
            )
        )

    from personal_markets.agents.intervention_critic import parse_weekly_application_intent

    app_intent = parse_weekly_application_intent(cleaned)
    if app_intent is not None:
        changes.append(
            TypedInterventionChange(
                metric="applications_per_week",
                operation=app_intent.operation,
                value=app_intent.value,
                unit="count/week",
                frequency="weekly",
                provenance="USER_ASSUMPTION",
            )
        )
    else:
        for match in _APPLICATIONS.finditer(cleaned):
            period = (match.group(2) or "week").lower()
            metric = "applications_per_week" if period == "week" else "applications_per_month"
            changes.append(
                TypedInterventionChange(
                    metric=metric,
                    operation="add",
                    value=_parse_number(match.group(1)),
                    unit=f"count/{period}",
                    frequency=period,
                    provenance="USER_ASSUMPTION",
                )
            )

    for match in _WEEKLY_KM.finditer(cleaned):
        changes.append(
            TypedInterventionChange(
                metric="weekly_running_km",
                operation="set",
                value=_parse_number(match.group(1)),
                unit="km/week",
                frequency="weekly",
                provenance="USER_ASSUMPTION",
            )
        )

    for match in _RUN_DAYS.finditer(cleaned):
        changes.append(
            TypedInterventionChange(
                metric="running_days_per_week",
                operation="set",
                value=_parse_number(match.group(1)),
                unit="days/week",
                frequency="weekly",
                provenance="USER_ASSUMPTION",
            )
        )

    for match in _BURN.finditer(cleaned):
        period = (match.group(2) or "month").lower()
        changes.append(
            TypedInterventionChange(
                metric="burn_monthly" if period == "month" else f"burn_{period}",
                operation="set",
                value=_parse_number(match.group(1)),
                unit=f"currency/{period}",
                frequency=period,
                provenance="USER_ASSUMPTION",
            )
        )

    if "invest" in cleaned.lower() or "contribution" in cleaned.lower() or "$" in cleaned:
        money_match = _MONEY.search(cleaned)
        if money_match:
            period = (money_match.group(2) or "month").lower()
            metric = "monthly_contribution" if period == "month" else f"contribution_per_{period}"
            changes.append(
                TypedInterventionChange(
                    metric=metric,
                    operation="set",
                    value=_parse_number(money_match.group(1)),
                    unit=f"currency/{period}",
                    frequency=period,
                    provenance="USER_ASSUMPTION",
                )
            )

    if not changes:
        unsupported.append("no supported intervention pattern matched")

    return ParsedIntervention(
        raw_text=text,
        changes=tuple(changes),
        unsupported=tuple(unsupported),
    )
