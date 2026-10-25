# ruff: noqa: E501
"""Strategy insight contract and deterministic validators. No domain templates."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from personal_markets.goals.domain import GoalContract

ModelStatus = Literal["MODELED", "UNPRICED", "NEEDS_DATA"]
_PROBABILITY = re.compile(
    r"\b(probability|odds|uplift_pp|percentage points?|\+\s*\d+(?:\.\d+)?\s*%|"
    r"\d+(?:\.\d+)?\s*percentage[- ]points?)\b",
    re.I,
)
_HTTP = re.compile(r"https?://[^\s)>\]]+", re.I)

STRATEGY_KINDS = frozenset(
    {
        "strategic_advice",
        "opportunity_discovery",
        "exploratory_hypothetical",
        "compare_alternatives",
    }
)


class StrategyInsight(BaseModel):
    title: str
    description: str
    why_it_might_help: str
    why_this_fits: str
    next_step: str
    evidence_to_collect: str
    constraints: str = ""
    model_status: ModelStatus = "UNPRICED"
    grounded_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class StrategyProposal(BaseModel):
    understood_question: str = ""
    insights: list[StrategyInsight] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    research_claims: list[str] = Field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _authorized_blob(parts: list[str]) -> str:
    return _norm(" \n ".join(part for part in parts if part and part.strip()))


def _fact_supported(fact: str, authorized: str) -> bool:
    token = _norm(fact)
    if len(token) < 8:
        return False
    if token in authorized:
        return True
    words = [word for word in re.findall(r"[a-z0-9]{4,}", token) if word not in {"this", "that", "with", "from"}]
    if len(words) < 2:
        return False
    return sum(word in authorized for word in words) >= max(2, (len(words) + 1) // 2)


def _allowed_source(source: str, research_sources: set[str]) -> bool:
    raw = source.strip()
    if not raw:
        return False
    if _HTTP.search(raw):
        host = urlparse(raw).netloc.lower()
        return any(host and host in item.lower() for item in research_sources) or raw in research_sources
    return True


def validate_strategy_proposal(
    proposal: StrategyProposal,
    *,
    goal: GoalContract,
    question: str,
    evidence_summaries: list[str],
    research_sources: list[str] | None = None,
    allowed_metrics: set[str] | None = None,
) -> tuple[list[StrategyInsight], list[str]]:
    """Keep model ideas that stay grounded. Drop invented facts, URLs, and fake uplifts."""

    authorized = _authorized_blob(
        [question, goal.title, str(goal.success_definition), *(evidence_summaries or []), *(research_sources or [])]
    )
    research = set(research_sources or [])
    metrics = {item.lower() for item in (allowed_metrics or set())}
    kept: list[StrategyInsight] = []
    issues: list[str] = []
    seen: set[str] = set()
    for item in proposal.insights[:3]:
        prose = " ".join(
            [
                item.title,
                item.description,
                item.why_it_might_help,
                item.why_this_fits,
                item.next_step,
                item.evidence_to_collect,
                item.constraints,
            ]
        )
        if _PROBABILITY.search(prose):
            issues.append(f"Dropped “{item.title}”: numerical probability language is not allowed.")
            continue
        status = item.model_status
        if status == "MODELED" and not any(metric in _norm(prose) for metric in metrics):
            status = "UNPRICED"
        grounded: list[str] = []
        assumptions = list(item.assumptions)
        for fact in item.grounded_facts:
            if _fact_supported(fact, authorized):
                grounded.append(fact)
            else:
                assumptions.append(f"Unverified: {fact}")
                issues.append(f"Moved unsupported fact to assumptions for “{item.title}”.")
        sources = [source for source in item.sources if _allowed_source(source, research)]
        if len(item.sources) != len(sources):
            issues.append(f"Removed invented sources from “{item.title}”.")
        key = _norm(item.title)
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            item.model_copy(
                update={
                    "model_status": status,
                    "grounded_facts": grounded,
                    "assumptions": assumptions,
                    "sources": sources,
                }
            )
        )
    return kept, list(proposal.limitations) + issues


def percent_points(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100 if value <= 1 else value


def consumer_summary(
    *,
    kind: str,
    published_odds: float | None,
    comparison_odds: float | None,
    scenario_odds: float | None,
    improvement_pp: float | None,
    question: str,
    diagnostic_note: str | None = None,
) -> str:
    asked = question.strip() or "this change"
    published = percent_points(published_odds)
    comparison = percent_points(comparison_odds)
    scenario = percent_points(scenario_odds)
    if kind == "current_odds":
        if published is None:
            return "There is no published forecast to report yet."
        return (
            f"Your latest published odds are {published:.2f}%. "
            "That is the market number, not a What If scenario."
        )
    if kind == "evidence_report":
        return (
            "That sounds like something that already happened, not a hypothetical. "
            f"Confirm the date and metric if you want it stored as evidence for “{asked}”."
        )
    if kind == "diagnostic":
        return diagnostic_note or (
            "I can report the current priced baseline and recent evidence, "
            "but I will not invent a causal story the receipt does not support."
        )
    if kind == "reverse_planning":
        return "Use Reverse to search modeled levers for a target probability. Unmodeled actions stay unpriced."
    if kind in {"follow_up", "clarification_needed"}:
        return "This follow-up is missing the original action or baseline. Restate the full change."
    if scenario is None:
        return (
            "This is a strategy question. PlayItOut can reason about the idea without inventing "
            "a probability change."
        )
    published_label = f"{published:.0f}%" if published is not None else "unpublished"
    baseline = f"{comparison:.0f}%" if comparison is not None else "—"
    delta = (
        f"{improvement_pp:+.1f} percentage points"
        if improvement_pp is not None
        else "an unquantified shift"
    )
    return (
        f"You currently have published odds of {published_label}. Under the model's latest "
        f"recalculated assumptions, “{asked}” changes the comparison from {baseline} to "
        f"{scenario:.0f}%, {delta}. This is a modeled scenario, not a new published forecast."
    )
