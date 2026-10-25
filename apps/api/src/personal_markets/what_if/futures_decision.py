from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from personal_markets.forecasting.finance import is_finance_goal
from personal_markets.forecasting.hiring import is_hiring_goal
from personal_markets.forecasting.running import is_running_goal
from personal_markets.forecasting.startup import is_startup_goal
from personal_markets.goals.domain import GoalContract

Timing = Literal["immediate", "soon", "later", "unspecified"]

CONTINUOUS_LABELS = (
    "Target reached",
    "Meaningful progress",
    "Current trajectory",
    "Downside outcome",
)
HIRING_LABELS = (
    "Offer received",
    "Final-stage pipeline",
    "Technical-stage pipeline",
    "Screening-stage pipeline",
    "No meaningful progress",
)
STARTUP_LABELS = (
    "Raise seed",
    "Bootstrap sustainably",
    "Stay employed, part-time startup",
    "Downside / return to job",
)
GENERIC_LABELS = (
    "Strong upside path",
    "Steady progress path",
    "Downside / delay path",
)


@dataclass(frozen=True, slots=True)
class TypedDecision:
    action: str
    alternative: str | None
    timing: Timing
    constraints: tuple[str, ...]
    raw_text: str


@dataclass(frozen=True, slots=True)
class ParsedDecision:
    raw_text: str
    decision: TypedDecision | None
    scenario_labels: tuple[str, ...]
    unsupported: tuple[str, ...]


_QUIT_JOB = re.compile(r"\b(quit|leave|resign)\b.*\b(job|internship|role|position)\b", re.I)
_STARTUP = re.compile(r"\b(startup|founder|full[- ]time\s+startup|my\s+company)\b", re.I)
_SAVE = re.compile(r"\b(save|invest|contribute)\b", re.I)
_RUN = re.compile(r"\b(run|running|train)\b", re.I)
_APPLY = re.compile(r"\b(applications?|apply|pipeline)\b", re.I)


def scenario_labels_for_goal(goal: GoalContract) -> tuple[str, ...]:
    if is_startup_goal(goal):
        return STARTUP_LABELS
    if is_hiring_goal(goal):
        return HIRING_LABELS
    if is_finance_goal(goal) or is_running_goal(goal):
        return CONTINUOUS_LABELS
    return GENERIC_LABELS


def _timing(text: str) -> Timing:
    if re.search(r"\b(now|immediately|today)\b", text, re.I):
        return "immediate"
    if re.search(r"\b(next month|soon|this quarter)\b", text, re.I):
        return "soon"
    if re.search(r"\b(later|eventually|next year)\b", text, re.I):
        return "later"
    return "unspecified"


def _typed_decision_from_text(cleaned: str) -> TypedDecision | None:
    timing = _timing(cleaned)
    if _QUIT_JOB.search(cleaned) and _STARTUP.search(cleaned):
        return TypedDecision(
            action="leave_job",
            alternative="full_time_startup",
            timing=timing,
            constraints=(),
            raw_text=cleaned,
        )
    if _SAVE.search(cleaned):
        return TypedDecision(
            action="increase_savings",
            alternative=None,
            timing=timing,
            constraints=(),
            raw_text=cleaned,
        )
    if _RUN.search(cleaned):
        return TypedDecision(
            action="adjust_training",
            alternative=None,
            timing=timing,
            constraints=(),
            raw_text=cleaned,
        )
    if _APPLY.search(cleaned):
        return TypedDecision(
            action="pipeline_change",
            alternative=None,
            timing=timing,
            constraints=(),
            raw_text=cleaned,
        )
    if _STARTUP.search(cleaned):
        return TypedDecision(
            action="adjust_startup_effort",
            alternative=None,
            timing=timing,
            constraints=(),
            raw_text=cleaned,
        )
    return TypedDecision(
        action="adjust_plan",
        alternative=None,
        timing=timing,
        constraints=(),
        raw_text=cleaned,
    )


def _regex_labels(cleaned: str) -> tuple[str, ...]:
    if _QUIT_JOB.search(cleaned) and _STARTUP.search(cleaned):
        return (
            "Stay employed, part-time startup",
            "Leave job, full-time startup",
            "Return to job search",
            "Downside outcome",
        )
    if _SAVE.search(cleaned) or _RUN.search(cleaned):
        return CONTINUOUS_LABELS
    if _APPLY.search(cleaned):
        return HIRING_LABELS
    if _STARTUP.search(cleaned):
        return STARTUP_LABELS
    return ()


def parse_futures_decision(
    text: str,
    goal: GoalContract | None = None,
) -> ParsedDecision:
    cleaned = text.strip()
    if not cleaned:
        return ParsedDecision(
            raw_text=text,
            decision=None,
            scenario_labels=(),
            unsupported=("empty decision text",),
        )

    family_labels = scenario_labels_for_goal(goal) if goal is not None else ()
    decision = _typed_decision_from_text(cleaned)
    if family_labels:
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=family_labels,
            unsupported=(),
        )

    labels = _regex_labels(cleaned)
    if labels:
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=labels,
            unsupported=(),
        )
    return ParsedDecision(
        raw_text=cleaned,
        decision=decision,
        scenario_labels=GENERIC_LABELS,
        unsupported=(),
    )
