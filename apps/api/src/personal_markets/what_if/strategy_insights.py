# ruff: noqa: E501
"""Strategy insight contract and deterministic validators. No domain templates."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from personal_markets.goals.domain import GoalContract

ModelStatus = Literal["MODELED", "UNPRICED", "NEEDS_DATA"]
# Invented numeric effects only. Mentioning "odds" or "probability" in a disclaimer
# must not drop a valid unpriced recommendation.
_INVENTED_EFFECT = re.compile(
    r"\buplift_pp\b|"
    r"\+\s*\d+(?:\.\d+)?\s*%|"
    r"\d+(?:\.\d+)?\s*percentage[- ]points?|"
    r"p\s*\(\s*[\w]+\s*\)\s*=\s*\d|"
    r"\b(?:odds|probability|chance|likelihood)\s+(?:of|to)\s+\d|"
    r"\b(?:raise|raises|increase|increases|adds?|boosts?)\s+"
    r"(?:your\s+)?(?:odds|probability|chance|likelihood).{0,32}\d",
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
    modeled_metric: str | None = None
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


_PERSONAL_CLAIM = re.compile(
    r"\b("
    r"you have|you've got|you interned|you used to work|"
    r"your former (?:manager|boss|intern|colleague|professor)|"
    r"your (?:cousin|mentor|referrer|manager) |"
    r"authorized (?:notes|evidence) (?:already )?mention|"
    r"recorded (?:progress|notes) include|"
    r"a named (?:referrer|manager|investor|mentor)"
    r")\b",
    re.I,
)
_CAUSAL_CERTAINTY = re.compile(
    r"\b(will definitely|guarantees?|proven to (?:raise|increase)|causes a \d|"
    r"will raise (?:your )?(?:odds|probability))\b",
    re.I,
)


def _allowed_source(source: str, research_sources: set[str]) -> bool:
    raw = source.strip()
    if not raw or not research_sources:
        return False
    blob = _norm(" ".join(research_sources))
    token = _norm(raw)
    if _HTTP.search(raw):
        host = urlparse(raw).netloc.lower()
        return bool(host) and any(host in item.lower() for item in research_sources)
    return token in blob or any(token in _norm(item) or _norm(item) in token for item in research_sources)


def _modeled_status(item: StrategyInsight, metrics: set[str], issues: list[str]) -> ModelStatus:
    if item.model_status != "MODELED":
        return item.model_status
    metric = (item.modeled_metric or "").strip().lower()
    step = _norm(item.next_step)
    readable = metric.replace("_", " ")
    named = bool(metric) and metric in metrics and (metric in step or readable in step)
    numeric = bool(re.search(r"\d", item.next_step))
    if named and numeric:
        return "MODELED"
    issues.append(
        f"“{item.title}” is unpriced: MODELED requires a verified numeric contract "
        "on a supported intervention, not a metric mentioned in prose."
    )
    return "UNPRICED"


def _qualify_personal_claims(prose: str, authorized: str, assumptions: list[str], issues: list[str], title: str) -> str:
    if not _PERSONAL_CLAIM.search(prose):
        return prose
    sentences = re.split(r"(?<=[.!?])\s+", prose)
    kept: list[str] = []
    for sentence in sentences:
        if not _PERSONAL_CLAIM.search(sentence):
            kept.append(sentence)
            continue
        if _fact_supported(sentence, authorized):
            kept.append(sentence)
            continue
        assumptions.append(f"Unverified: {sentence.strip()}")
        issues.append(f"Qualified unsupported personal claim in “{title}”.")
        kept.append("This depends on a fact that is not in authorized evidence.")
    return " ".join(part for part in kept if part)


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
        if _INVENTED_EFFECT.search(prose) or _CAUSAL_CERTAINTY.search(prose):
            issues.append(
                f"Dropped “{item.title}”: numerical probability or unsupported causal certainty is not allowed."
            )
            continue
        grounded: list[str] = []
        assumptions = list(item.assumptions)
        for fact in item.grounded_facts:
            if _fact_supported(fact, authorized):
                grounded.append(fact)
            else:
                assumptions.append(f"Unverified: {fact}")
                issues.append(f"Moved unsupported fact to assumptions for “{item.title}”.")
        why_fits = _qualify_personal_claims(
            item.why_this_fits, authorized, assumptions, issues, item.title
        )
        description = _qualify_personal_claims(
            item.description, authorized, assumptions, issues, item.title
        )
        why_help = _qualify_personal_claims(
            item.why_it_might_help, authorized, assumptions, issues, item.title
        )
        next_step = _qualify_personal_claims(
            item.next_step, authorized, assumptions, issues, item.title
        )
        sources = [source for source in item.sources if _allowed_source(source, research)]
        if len(item.sources) != len(sources):
            issues.append(f"Removed invented sources from “{item.title}”.")
        status = _modeled_status(item, metrics, issues)
        key = _norm(item.title)
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            item.model_copy(
                update={
                    "model_status": status,
                    "modeled_metric": item.modeled_metric if status == "MODELED" else None,
                    "why_this_fits": why_fits,
                    "why_it_might_help": why_help,
                    "next_step": next_step,
                    "description": description,
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
