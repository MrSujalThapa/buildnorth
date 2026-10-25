"""Deterministic What If request classification. No probabilities are assigned here."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

RequestKind = Literal[
    "quantitative_scenario",
    "evidence_report",
    "strategic_advice",
    "opportunity_discovery",
    "compare_alternatives",
    "reverse_planning",
    "current_odds",
    "exploratory_hypothetical",
    "diagnostic",
    "follow_up",
    "clarification_needed",
]

_WHAT_IF = re.compile(r"\bwhat\s*if\b|\bhypothetic", re.I)
_EVIDENCE_PAST = re.compile(
    r"\b(i|we)\s+(got|had|applied|submitted|finished|ran|saved|practiced|sent|"
    r"completed|won|pitched|met|talked|received|landed|booked|offered)\b"
    r"|\bthis week\b.*\b(interview|application|session|rejection)"
    r"|\b(yesterday|last week|already|i actually)\b"
    r"|\bformer manager\b",
    re.I,
)
_PLANNED = re.compile(
    r"\b(plan to|i(?:'m| am) going to|i will|tomorrow|i might|i think|"
    r"around \d|pretty sure|roughly|i may)\b",
    re.I,
)
_OPPORTUNITY = re.compile(
    r"\b(overlooking|missing|smarter|highest leverage|who could help|"
    r"leverage|creative ways|haven't tried|what would you do|"
    r"opportunit|underused|warm intro|how can i get|traction)\b",
    re.I,
)
_STRATEGIC = re.compile(
    r"\b(should i|would i be better|what's the play|what do (u|you) think|"
    r"am i cooked|what now|is this even doable|the play here)\b",
    re.I,
)
_COMPARE = re.compile(
    r"\b(or|versus|vs\.?|instead of|rather than|sacrifice|more useful than)\b", re.I
)
_REVERSE = re.compile(
    r"\b(above|over|reach|hit|get (my |the )?chances?|how could i realistically)\b.*\b\d{2,3}\s*%"
    r"|\bhow (could|can|do) i .*(90|95|99)\s*%"
    r"|\bminimum i need\b",
    re.I,
)
_CURRENT = re.compile(
    r"\b(odds|chances|probability)\b.*\b(now|rn|currently|right now)\b|\bwhat are my odds\b", re.I
)
_DIAGNOSTIC = re.compile(
    r"\bwhy (aren'?t|are not|did|isn'?t|isn't)\b|\bholding me back\b|"
    r"\bstrategy actually working\b|\bweakest\b|\bchange your mind\b|"
    r"\bnot making progress\b|\bworked harder\b",
    re.I,
)
_FOLLOW_UP = re.compile(
    r"^(okay|ok|nah|actually|what about|make it|do \d+|add \d+|instead)\b"
    r"|\bdo \d+ instead\b|\btwice as (many|much)\b|\bincrease it by\b",
    re.I,
)
_QUANT_RATE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(applications?|jobs?|hours?|sessions?|km|miles?|customers?|books?)\b"
    r"|\b(double|twice|additional|more|extra)\b",
    re.I,
)
_EXPLORATORY = re.compile(
    r"\b(referrals?|referred|founders?|professor|cancels?|injur\w*|churns?|"
    r"unexpected|interview goes badly|lose my internship|week off|"
    r"delay my launch|conference)\b",
    re.I,
)


class ClassifiedRequest(BaseModel):
    kind: RequestKind
    uncertain: bool = False
    needs_confirmation: bool = False
    reason: str = ""
    notes: list[str] = Field(default_factory=list)


def classify_what_if_request(text: str) -> ClassifiedRequest:
    raw = text.strip()
    if not raw:
        return ClassifiedRequest(kind="clarification_needed", reason="Empty question.")
    uncertain = bool(_PLANNED.search(raw))
    if uncertain and not _WHAT_IF.search(raw):
        return ClassifiedRequest(
            kind="evidence_report",
            uncertain=True,
            needs_confirmation=False,
            reason="Sounds like an intention or guess, not a confirmed observation.",
        )
    if _CURRENT.search(raw) and not _WHAT_IF.search(raw):
        return ClassifiedRequest(
            kind="current_odds", reason="Asking for published odds, not a scenario."
        )
    if _DIAGNOSTIC.search(raw):
        return ClassifiedRequest(
            kind="diagnostic", reason="Asking why the forecast or plan looks stuck."
        )
    if _REVERSE.search(raw):
        return ClassifiedRequest(
            kind="reverse_planning", reason="Target-odds search rather than a single lever."
        )
    if _OPPORTUNITY.search(raw):
        return ClassifiedRequest(
            kind="opportunity_discovery",
            reason="Looking for unused leverage rather than a numeric intervention.",
        )
    if _COMPARE.search(raw) and (
        _STRATEGIC.search(raw) or "would" in raw.lower() or "should" in raw.lower()
    ):
        return ClassifiedRequest(
            kind="compare_alternatives", reason="Tradeoff between alternatives."
        )
    past = bool(_EVIDENCE_PAST.search(raw))
    hypothetical = bool(_WHAT_IF.search(raw))
    completed = bool(
        re.search(r"\b(yesterday|last week|already|i actually|this week)\b", raw, re.I)
    )
    if past and (not hypothetical or completed):
        return ClassifiedRequest(
            kind="evidence_report",
            uncertain=uncertain,
            needs_confirmation=not uncertain,
            reason="Describes something that already happened.",
        )
    if _FOLLOW_UP.search(raw) and not hypothetical:
        return ClassifiedRequest(
            kind="follow_up",
            reason="Follow-up quantity without a stated baseline or prior action.",
        )
    if _STRATEGIC.search(raw) and not _QUANT_RATE.search(raw):
        return ClassifiedRequest(
            kind="strategic_advice", reason="Asking what to do, not a priced lever."
        )
    if _EXPLORATORY.search(raw) and not re.search(r"\b\d+\s+applications?\b", raw, re.I):
        return ClassifiedRequest(
            kind="exploratory_hypothetical",
            reason="Useful scenario, but no calibrated numeric mapping is implied.",
        )
    if hypothetical and re.search(r"\b(that|it)\b", raw, re.I) and not _QUANT_RATE.search(raw):
        return ClassifiedRequest(
            kind="follow_up",
            reason="The referenced action is missing; restate the full change.",
        )
    relative = bool(
        (_QUANT_RATE.search(raw) or hypothetical)
        and re.search(r"\b(twice as|double|increase it by|instead of)\b", raw, re.I)
        and not re.search(r"\binstead of \d+.*\bdo \d+\b|\b\d+\s+instead of\b", raw, re.I)
        and re.search(r"\btwice as|double my\b", raw, re.I)
        and not re.search(r"\b\d+\b", raw)
    )
    if relative:
        return ClassifiedRequest(
            kind="clarification_needed",
            reason="Relative change needs a known baseline quantity.",
        )
    if _QUANT_RATE.search(raw) or hypothetical:
        return ClassifiedRequest(
            kind="quantitative_scenario", reason="Looks like a numeric plan change."
        )
    if _FOLLOW_UP.search(raw):
        return ClassifiedRequest(
            kind="follow_up", reason="Incomplete follow-up; missing the referenced action."
        )
    return ClassifiedRequest(
        kind="strategic_advice",
        reason="No modeled quantity was stated; treat as a strategy question.",
    )
