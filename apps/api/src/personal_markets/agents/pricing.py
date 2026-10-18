from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from personal_markets.forecasting.registry import OuladCompletionApplicabilityPolicy
from personal_markets.ports import GoalArchitectProposal, PricingResult


def price_goal(
    proposal: GoalArchitectProposal,
    evidence_ids: list[str],
    agent_run_ids: dict[str, str],
    research_source_ids: list[str],
) -> PricingResult:
    """OULAD applicability gate. BaselineForecastService is the numerical authority."""
    policy = OuladCompletionApplicabilityPolicy()
    checkpoint = _checkpoint(proposal)
    decision = policy.evaluate(proposal.goal_type, proposal.success_metric, checkpoint)
    limitations = list(decision.reasons)
    if not decision.applicable:
        limitations.append(
            "No calibrated or anchored model currently applies to this goal; "
            "the market stays unpriced."
        )
        return PricingResult(
            priced=False,
            forecast_status="EXPLORATORY",
            model_version=None,
            limitations=limitations,
            receipt=_receipt(
                priced=False,
                proposal=proposal,
                evidence_ids=evidence_ids,
                agent_run_ids=agent_run_ids,
                research_source_ids=research_source_ids,
                status="EXPLORATORY",
                limitations=limitations,
            ),
        )
    limitations.append(
        "OULAD path is applicable only with frozen checkpoint features, which this goal lacks."
    )
    return PricingResult(
        priced=False,
        forecast_status="EXPLORATORY",
        model_version="oulad_completion_v1",
        limitations=limitations,
        receipt=_receipt(
            priced=False,
            proposal=proposal,
            evidence_ids=evidence_ids,
            agent_run_ids=agent_run_ids,
            research_source_ids=research_source_ids,
            status="EXPLORATORY",
            limitations=limitations,
        ),
    )


def _checkpoint(proposal: GoalArchitectProposal) -> int:
    target = proposal.success_target
    try:
        return int(target)
    except (TypeError, ValueError):
        return -1


def _receipt(
    *,
    priced: bool,
    proposal: GoalArchitectProposal,
    evidence_ids: list[str],
    agent_run_ids: dict[str, str],
    research_source_ids: list[str],
    status: str,
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "receipt_version": 1,
        "priced": priced,
        "goal_metric": proposal.success_metric,
        "goal_type": proposal.goal_type,
        "forecast_status": status,
        "model": {"family": "none" if not priced else "oulad_completion", "version": None},
        "normalized_evidence_ids": evidence_ids,
        "research_source_ids": research_source_ids,
        "agent_run_ids": agent_run_ids,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": str(uuid4()),
        "limitations": limitations,
        "raw_probability": None,
        "calibrated_probability": None,
    }


def needs_research(proposal: GoalArchitectProposal) -> bool:
    if proposal.research_required:
        return True
    blob = " ".join(
        [
            proposal.title,
            proposal.success_metric,
            proposal.success_target,
            proposal.model_family_compatibility,
        ]
    ).lower()
    tokens = (
        "admission",
        "waterloo",
        "university",
        "offer",
        "interview",
        "company",
        "hiring",
        "oulad",
        "course_completion",
    )
    return any(token in blob for token in tokens)
