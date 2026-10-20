from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from personal_markets.agents.critic import deterministic_critic_decision
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.inputs_builder import build_numeric_inputs, proposal_from_goal
from personal_markets.forecasting.repository import history_point
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import CriticArtifact, EvidenceEventProposal, GoalArchitectProposal


@dataclass(frozen=True, slots=True)
class RepriceResult:
    status: str
    reason: str | None = None
    probability: float | None = None
    receipt: dict[str, Any] | None = None


def _evidence_proposals(events: list[NormalizedEvidence]) -> list[EvidenceEventProposal]:
    proposals: list[EvidenceEventProposal] = []
    for item in events:
        observed = item.observed_at.isoformat() if item.observed_at else "unknown"
        source_type = item.provenance.source_type
        proposals.append(
            EvidenceEventProposal(
                event_type=item.event_type,
                domain=item.domain,
                metric=item.metric,
                numeric_value=item.numeric_value,
                categorical_value=item.categorical_value,
                unit=item.unit,
                observed_at=observed,
                source_type=source_type,
                summary=item.summary,
                observation_kind=item.provenance.observation_kind,
                event_identity=item.provenance.event_identity,
            )
        )
    return proposals


def _research_ids(
    goal: GoalContract, proposal: GoalArchitectProposal, numeric: NumericInputs | None
) -> list[str]:
    from personal_markets.forecasting.finance import is_finance_goal
    from personal_markets.forecasting.running import is_running_goal
    from personal_markets.forecasting.startup import is_startup_goal

    research_ids: list[str] = []
    from personal_markets.forecasting.hiring import is_hiring_goal

    if numeric is not None and is_hiring_goal(goal, proposal):
        research_ids.append("hiring_funnel_rates.json")
    if numeric is not None and is_finance_goal(goal, proposal):
        research_ids.append("net_worth_assumptions.json")
    if numeric is not None and is_running_goal(goal, proposal):
        research_ids.append("running_performance_assumptions.json")
    if numeric is not None and is_startup_goal(goal, proposal):
        research_ids.append("startup_outcome_priors.json")
    return research_ids


class BaselineRepriceService:
    """Recompute and publish baseline forecasts when evidence changes outside the agent graph."""

    def __init__(
        self,
        goals: GoalService,
        evidence: EvidenceService,
        forecasts: BaselineForecastService,
        owner_id: UUID | None = None,
    ) -> None:
        self._goals = goals
        self._evidence = evidence
        self._forecasts = forecasts
        self._owner_id = owner_id

    async def publish_if_priceable(self, goal_id: UUID) -> RepriceResult:
        goal = await self._goals.get_goal(goal_id, owner_id=self._owner_id)
        proposal = proposal_from_goal(goal)
        events = await self._evidence.list_for_goal(goal_id)
        evidence_ids = [str(item.evidence_id) for item in events if item.evidence_id]
        if not evidence_ids:
            return RepriceResult(status="no_evidence", reason="No evidence is linked to this goal.")

        numeric = build_numeric_inputs(goal, proposal, events)
        pricing = self._forecasts.compute(
            goal,
            proposal,
            evidence_ids,
            {},
            _research_ids(goal, proposal, numeric),
            numeric,
        )
        if not pricing.priced or pricing.raw_probability is None:
            reason = (
                pricing.limitations[0]
                if pricing.limitations
                else "The model could not price this goal."
            )
            return RepriceResult(
                status="not_priced",
                reason=reason,
                receipt=dict(pricing.receipt),
            )

        issues = self._forecasts.deterministic_issues(
            _evidence_proposals(events),
            evidence_ids,
            pricing,
        )
        critic = deterministic_critic_decision(issues, pricing)
        if critic is None:
            critic = CriticArtifact(
                decision="publish",
                issues=[],
                limitations=pricing.limitations,
                required_actions=[],
            )
        if critic.decision == "withhold":
            if self._owner_id is not None:
                await self._goals.record_publication(goal_id, self._owner_id, critic, "withheld")
            return RepriceResult(
                status="withheld",
                reason=critic.issues[0] if critic.issues else "The critic withheld publication.",
                receipt=dict(pricing.receipt),
            )

        point = history_point(goal, pricing)
        if point is not None:
            history = await self._forecasts.published_history(goal_id)
            if any(
                item.material_hash == point.material_hash
                or item.evidence_watermark == point.evidence_watermark
                for item in history
            ):
                matched = next(
                    item
                    for item in history
                    if item.material_hash == point.material_hash
                    or item.evidence_watermark == point.evidence_watermark
                )
                return RepriceResult(
                    status="unchanged",
                    probability=matched.probability,
                    receipt=dict(pricing.receipt),
                )

        status = await self._forecasts.publish(goal, pricing, critic)
        if self._owner_id is not None:
            await self._goals.record_publication(goal_id, self._owner_id, critic, status)
        return RepriceResult(
            status=status,
            probability=pricing.raw_probability,
            receipt=dict(pricing.receipt),
        )
