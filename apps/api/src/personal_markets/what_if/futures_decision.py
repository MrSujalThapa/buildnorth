from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Timing = Literal["immediate", "soon", "later", "unspecified"]


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


def parse_futures_decision(text: str) -> ParsedDecision:
    cleaned = text.strip()
    if not cleaned:
        return ParsedDecision(
            raw_text=text,
            decision=None,
            scenario_labels=(),
            unsupported=("empty decision text",),
        )

    constraints: list[str] = []
    timing: Timing = "unspecified"
    if re.search(r"\b(now|immediately|today)\b", cleaned, re.I):
        timing = "immediate"
    elif re.search(r"\b(next month|soon|this quarter)\b", cleaned, re.I):
        timing = "soon"
    elif re.search(r"\b(later|eventually|next year)\b", cleaned, re.I):
        timing = "later"

    if _QUIT_JOB.search(cleaned) and _STARTUP.search(cleaned):
        decision = TypedDecision(
            action="leave_job",
            alternative="full_time_startup",
            timing=timing,
            constraints=tuple(constraints),
            raw_text=cleaned,
        )
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=(
                "Stay employed, part-time startup",
                "Leave job, full-time startup",
                "Return to job search",
                "Downside outcome",
            ),
            unsupported=(),
        )

    if _SAVE.search(cleaned):
        decision = TypedDecision(
            action="increase_savings",
            alternative=None,
            timing=timing,
            constraints=tuple(constraints),
            raw_text=cleaned,
        )
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=(
                "Target reached",
                "Meaningful progress",
                "Current trajectory",
                "Downside outcome",
            ),
            unsupported=(),
        )

    if _RUN.search(cleaned):
        decision = TypedDecision(
            action="adjust_training",
            alternative=None,
            timing=timing,
            constraints=tuple(constraints),
            raw_text=cleaned,
        )
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=(
                "Target reached",
                "Meaningful progress",
                "Current trajectory",
                "Downside outcome",
            ),
            unsupported=(),
        )

    if _APPLY.search(cleaned):
        decision = TypedDecision(
            action="pipeline_change",
            alternative=None,
            timing=timing,
            constraints=tuple(constraints),
            raw_text=cleaned,
        )
        return ParsedDecision(
            raw_text=cleaned,
            decision=decision,
            scenario_labels=(
                "Offer received",
                "Final-stage pipeline",
                "Technical-stage pipeline",
                "No meaningful progress",
            ),
            unsupported=(),
        )

    return ParsedDecision(
        raw_text=cleaned,
        decision=None,
        scenario_labels=(),
        unsupported=("no supported decision taxonomy matched",),
    )
