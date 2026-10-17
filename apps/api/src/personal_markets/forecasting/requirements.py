"""What a model family needs before a goal can be priced, and whether it has it.

Model families declare the state variables they consume. Evidence arrives with
free-form metric names chosen by the Evidence Agent, so this module resolves those
names onto the declared vocabulary and reports precisely what is still missing. That
report is what lets the product say "we need your current balance" instead of an
unexplained "Unpriced".

Nothing here produces or adjusts a probability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from personal_markets.evidence.domain import NormalizedEvidence

PriceabilityStatus = Literal["PRICED", "ASSUMPTION_REQUIRED", "NOT_PRICED"]

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "per",
        "my",
        "your",
        "current",
        "total",
        "amount",
        "value",
        "usd",
        "cad",
        "eur",
        "gbp",
    }
)
# A requirement only claims an evidence metric when the overlap is decisive; below
# this the metric is left for another requirement or reported as missing.
_MATCH_THRESHOLD = 0.6


def tokenize(text: str) -> frozenset[str]:
    return frozenset(token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS)


@dataclass(frozen=True, slots=True)
class StateRequirement:
    """One numerical input a model family needs, and how a user can supply it."""

    key: str
    label: str
    unit: str
    why: str
    aliases: tuple[str, ...] = ()
    derived_from: tuple[tuple[str, ...], ...] = ()
    required: bool = True
    example: str | None = None
    suggested_sources: tuple[str, ...] = ()

    def match_tokens(self) -> frozenset[str]:
        parts = [self.key, self.label, *self.aliases]
        return frozenset().union(*(tokenize(part) for part in parts))

    def core_tokens(self) -> frozenset[str]:
        return tokenize(self.key) or tokenize(self.label)


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    key: str
    value: float
    source: str
    detail: str
    evidence_id: str | None = None
    matched_metric: str | None = None


@dataclass(frozen=True, slots=True)
class MissingRequirement:
    key: str
    label: str
    unit: str
    why: str
    example: str | None
    suggested_sources: tuple[str, ...]
    derived_from: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class StateResolution:
    """Which declared state variables are satisfied, and by what."""

    resolved: dict[str, ResolvedValue] = field(default_factory=dict)
    missing: tuple[MissingRequirement, ...] = ()
    unmatched_evidence: tuple[str, ...] = ()

    @property
    def satisfied(self) -> bool:
        return not self.missing

    def value(self, key: str) -> float | None:
        found = self.resolved.get(key)
        return None if found is None else found.value

    def sources(self) -> dict[str, str]:
        return {key: item.source for key, item in self.resolved.items()}


def _score(requirement: StateRequirement, metric: str) -> float:
    """How strongly an evidence metric name matches a declared requirement."""
    metric_tokens = tokenize(metric)
    if not metric_tokens:
        return 0.0
    normalized = metric.strip().lower()
    if normalized == requirement.key.lower() or normalized in {
        alias.lower() for alias in requirement.aliases
    }:
        return 1.0
    core = requirement.core_tokens()
    if not core:
        return 0.0
    overlap = metric_tokens & requirement.match_tokens()
    if not overlap:
        return 0.0
    # Reward covering the requirement's core meaning without penalising extra
    # qualifiers the Evidence Agent may add (e.g. "emergency_fund_balance").
    covered = len(core & metric_tokens) / len(core)
    precision = len(overlap) / len(metric_tokens)
    return 0.7 * covered + 0.3 * precision


def _source_label(item: NormalizedEvidence) -> str:
    """A number the user typed is not an observation, and must not be labelled as one."""
    if item.provenance.observed_vs_entered == "user_entered":
        return "USER_ENTERED"
    return "REAL_USER_EVIDENCE"


def resolve_state(
    requirements: tuple[StateRequirement, ...],
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
) -> StateResolution:
    """Map evidence and explicit user assumptions onto the declared vocabulary."""
    overrides = overrides or {}
    resolved: dict[str, ResolvedValue] = {}

    # Explicit user-supplied assumptions win over inferred evidence matches.
    by_key = {requirement.key: requirement for requirement in requirements}
    for key, raw in overrides.items():
        if key not in by_key or raw is None:
            continue
        try:
            resolved[key] = ResolvedValue(
                key=key,
                value=float(raw),
                source="USER_ASSUMPTION",
                detail="entered by the user",
            )
        except (TypeError, ValueError):
            continue

    # Latest observation wins per requirement; ties break on match strength.
    best: dict[str, tuple[float, NormalizedEvidence]] = {}
    claimed: set[int] = set()
    for index, item in enumerate(evidence):
        if item.numeric_value is None:
            continue
        scores = [
            (_score(requirement, item.metric), requirement)
            for requirement in requirements
            if requirement.key not in resolved
        ]
        scores = [pair for pair in scores if pair[0] >= _MATCH_THRESHOLD]
        if not scores:
            continue
        score, requirement = max(scores, key=lambda pair: pair[0])
        claimed.add(index)
        current = best.get(requirement.key)
        if current is None:
            best[requirement.key] = (score, item)
            continue
        current_score, current_item = current
        current_at = current_item.observed_at
        item_at = item.observed_at
        if current_at is not None and item_at is not None:
            if item_at > current_at or (item_at == current_at and score > current_score):
                best[requirement.key] = (score, item)
        elif score > current_score:
            best[requirement.key] = (score, item)

    for key, (_score_value, item) in best.items():
        assert item.numeric_value is not None
        resolved[key] = ResolvedValue(
            key=key,
            value=float(item.numeric_value),
            source=_source_label(item),
            detail=f"{item.metric} = {item.numeric_value:g}{f' {item.unit}' if item.unit else ''}",
            evidence_id=str(item.evidence_id) if item.evidence_id else None,
            matched_metric=item.metric,
        )

    # Derived routes run last so directly observed values always take precedence.
    for requirement in requirements:
        if requirement.key in resolved or not requirement.derived_from:
            continue
        for route in requirement.derived_from:
            if all(part in resolved for part in route):
                value = _derive(requirement.key, route, resolved)
                if value is None:
                    continue
                resolved[requirement.key] = ResolvedValue(
                    key=requirement.key,
                    value=value,
                    source="DERIVED",
                    detail=" - ".join(route),
                )
                break

    missing = tuple(
        MissingRequirement(
            key=requirement.key,
            label=requirement.label,
            unit=requirement.unit,
            why=requirement.why,
            example=requirement.example,
            suggested_sources=requirement.suggested_sources,
            derived_from=requirement.derived_from,
        )
        for requirement in requirements
        if requirement.required and requirement.key not in resolved
    )
    unmatched = tuple(
        item.metric
        for index, item in enumerate(evidence)
        if index not in claimed and item.numeric_value is not None
    )
    return StateResolution(resolved=resolved, missing=missing, unmatched_evidence=unmatched)


def _derive(key: str, route: tuple[str, ...], resolved: dict[str, ResolvedValue]) -> float | None:
    """Derivations are subtractive surpluses (inflow minus outflow)."""
    if len(route) != 2:
        return None
    inflow = resolved[route[0]].value
    outflow = resolved[route[1]].value
    _ = key
    return inflow - outflow


@dataclass(frozen=True, slots=True)
class PriceabilityReport:
    """Why a goal can or cannot be priced right now, in user-facing terms."""

    status: PriceabilityStatus
    model_family: str
    headline: str
    requirements: tuple[StateRequirement, ...]
    resolution: StateResolution
    reason: str | None = None

    @property
    def missing_labels(self) -> tuple[str, ...]:
        return tuple(item.label for item in self.resolution.missing)


def build_report(
    *,
    model_family: str,
    requirements: tuple[StateRequirement, ...],
    resolution: StateResolution,
    unsupported_reason: str | None = None,
) -> PriceabilityReport:
    if unsupported_reason is not None:
        return PriceabilityReport(
            status="NOT_PRICED",
            model_family=model_family,
            headline="This goal is outside the models we can price today.",
            requirements=requirements,
            resolution=resolution,
            reason=unsupported_reason,
        )
    if resolution.satisfied:
        return PriceabilityReport(
            status="PRICED",
            model_family=model_family,
            headline="Priced from your evidence.",
            requirements=requirements,
            resolution=resolution,
        )
    labels = [item.label for item in resolution.missing]
    joined = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" and {labels[-1]}"
    return PriceabilityReport(
        status="ASSUMPTION_REQUIRED",
        model_family=model_family,
        headline=f"Your goal is measurable, but we still need {joined}.",
        requirements=requirements,
        resolution=resolution,
        reason="missing_state",
    )
