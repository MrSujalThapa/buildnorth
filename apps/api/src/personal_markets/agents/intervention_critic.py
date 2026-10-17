from __future__ import annotations

from personal_markets.goals.domain import GoalContract
from personal_markets.ports import (
    InterventionAgentProposal,
    InterventionCriticArtifact,
    InterventionPricingStatus,
)
from personal_markets.what_if.intervention_registry import allowed_metrics

_PROBABILITY_TOKENS = ("probability", "odds", "likelihood", "uplift_pp", "percent_change")


def _is_probability_like(metric: str, unit: str) -> bool:
    haystack = f"{metric} {unit}".lower()
    return any(token in haystack for token in _PROBABILITY_TOKENS)


def critique_intervention(
    goal: GoalContract,
    proposal: InterventionAgentProposal,
) -> InterventionCriticArtifact:
    issues: list[str] = []
    limitations = list(proposal.limitations)
    pricing_status: InterventionPricingStatus = proposal.pricing_status
    permitted = allowed_metrics(goal)

    # The invariant is that no agent-authored number becomes a probability. Enforce it
    # on the structured changes, which are the only thing the simulator consumes.
    # Prose is display-only: a mechanism that explains itself using the word
    # "probability" is good writing, not a contract violation, and must not veto pricing.
    validated_changes = []
    for change in proposal.changes:
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
