from __future__ import annotations

import re

from personal_markets.goals.domain import GoalContract
from personal_markets.ports import (
    InterventionAgentProposal,
    InterventionCriticArtifact,
    InterventionPricingStatus,
)
from personal_markets.what_if.intervention_registry import allowed_metrics, composed_metric_units

_PROBABILITY_TOKENS = ("probability", "odds", "likelihood", "uplift_pp", "percent_change")
_APPLICATION_QUANTITY = re.compile(
    r"\b(?:(?:appl(?:y|ied|ying)\s+to\s+))?(\d+(?:\.\d+)?)\s+"
    r"(?:additional\s+|more\s+|extra\s+)?(?:job\s+)?applications?\b"
    r"|\bappl(?:y|ied|ying)\s+to\s+(\d+(?:\.\d+)?)\s+jobs?\b",
    re.I,
)


def _stated_application_quantity(text: str) -> float | None:
    match = _APPLICATION_QUANTITY.search(text)
    if match is None or re.search(r"\b(?:week|weekly)\b", text, re.I) is None:
        return None
    return float(match.group(1) or match.group(2))


def _is_probability_like(metric: str, unit: str) -> bool:
    haystack = f"{metric} {unit}".lower()
    return any(token in haystack for token in _PROBABILITY_TOKENS)


def critique_intervention(
    goal: GoalContract,
    proposal: InterventionAgentProposal,
    source_text: str | None = None,
) -> InterventionCriticArtifact:
    issues: list[str] = []
    limitations = list(proposal.limitations)
    pricing_status: InterventionPricingStatus = proposal.pricing_status
    permitted = allowed_metrics(goal)
    units = composed_metric_units(goal)

    # The invariant is that no agent-authored number becomes a probability. Enforce it
    # on the structured changes, which are the only thing the simulator consumes.
    # Prose is display-only: a mechanism that explains itself using the word
    # "probability" is good writing, not a contract violation, and must not veto pricing.
    validated_changes = []
    for change in proposal.changes:
        if source_text is not None and change.metric in {
            "applications_per_week",
            "weekly_application_rate",
        }:
            if re.search(r"\b(?:yesterday|last week|already)\b", source_text, re.I):
                issues.append(
                    "A completed application count is evidence, not a future What If action."
                )
                continue
            if re.search(r"\band\b", source_text, re.I) and re.search(
                r"\b(?:cold\s+emails?|network\w*|leetcode|study|gym)\b", source_text, re.I
            ):
                issues.append(
                    "This question combines a modeled application change with an "
                    "unmodeled action; ask about the application change separately."
                )
                continue
            if (
                re.search(r"\binstead\s+of\b", source_text, re.I)
                and len(re.findall(r"\d+(?:\.\d+)?", source_text)) > 1
            ):
                issues.append(
                    "The previous and proposed application rates are ambiguous; "
                    "state the new applications-per-week rate explicitly."
                )
                continue
            stated = _stated_application_quantity(source_text)
            if stated is None:
                issues.append(
                    "Cold emails and networking are not measured applications; "
                    "state an application count per week to model this change."
                )
                continue
            if abs(stated - change.value) > 1e-9:
                issues.append("The proposed weekly application count differs from your question.")
                continue
            is_delta = bool(re.search(r"\b(?:more|additional|extra)\b", source_text, re.I))
            if (is_delta and change.operation != "add") or (
                not is_delta and change.operation != "set"
            ):
                issues.append("Application changes must distinguish a new rate from an increase.")
                continue
        if source_text is not None and change.provenance in {
            "USER_ASSUMPTION",
            "EXPLORATION_ASSUMPTION",
        }:
            numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", source_text)]
            if not any(abs(value - change.value) < 1e-9 for value in numbers):
                issues.append(
                    f"Dropped `{change.metric}`: the proposed quantity was not in your question."
                )
                continue
        if _is_probability_like(change.metric, change.unit):
            issues.append(
                f"Dropped `{change.metric}`: execution likelihood comes from the observed "
                "behavior model, never from the intervention agent."
            )
            limitations.append(
                "Follow-through was taken from your behavior history rather than the "
                "proposed action."
            )
            continue
        if change.metric not in permitted:
            issues.append(f"Metric `{change.metric}` is not modeled for this goal family.")
            continue
        expected_unit = units.get(change.metric)
        if expected_unit is not None and change.unit.strip().lower() != expected_unit.lower():
            issues.append(
                f"Dropped `{change.metric}`: unit `{change.unit}` does not match the model "
                f"parameter unit `{expected_unit}`."
            )
            continue
        if change.provenance == "FITTED" and change.strength == "NOT_PRICED":
            issues.append(f"Change `{change.metric}` lacks defensible strength.")
            continue
        validated_changes.append(change)

    if validated_changes and pricing_status == "NOT_PRICED" and not proposal.unsupported:
        # Stripping a disallowed change must not discard the defensible mechanism that
        # survived alongside it.
        pricing_status = "PRICED"

    if not validated_changes and pricing_status == "PRICED":
        pricing_status = "NOT_PRICED"
        if not proposal.unsupported:
            limitations.append("No defensible state changes mapped to the numerical model.")

    approved = pricing_status in {"PRICED", "ASSUMPTION_REQUIRED"} and bool(validated_changes)
    if pricing_status == "ASSUMPTION_REQUIRED" and not validated_changes:
        approved = False
        pricing_status = "NOT_PRICED"

    if pricing_status == "NOT_PRICED":
        approved = False

    return InterventionCriticArtifact(
        approved=approved,
        pricing_status=pricing_status,
        validated_changes=validated_changes,
        issues=issues,
        limitations=limitations,
    )
