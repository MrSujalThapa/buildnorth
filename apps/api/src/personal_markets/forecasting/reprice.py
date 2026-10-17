from __future__ import annotations

from uuid import UUID

from personal_markets.agents.critic import deterministic_critic_decision
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import history_point
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import CriticArtifact, EvidenceEventProposal, GoalArchitectProposal
from personal_markets.what_if.baseline_state import proposal_from_goal


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
            )
        )
    return proposals


def _research_ids(goal: GoalContract, proposal: GoalArchitectProposal, numeric) -> list[str]:
    from personal_markets.forecasting.finance import is_finance_goal
    from personal_markets.forecasting.hiring import is_hiring_goal
    from personal_markets.forecasting.running import is_running_goal
    from personal_markets.forecasting.startup import is_startup_goal

    research_ids: list[str] = []
    if numeric is not None:
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
    ) -> None:
        self._goals = goals
        self._evidence = evidence
        self._forecasts = forecasts

    async def publish_if_priceable(self, goal_id: UUID) -> str:
        goal = await self._goals.get_goal(goal_id)
        proposal = proposal_from_goal(goal)
        events = await self._evidence.list_for_goal(goal_id)
        evidence_ids = [str(item.evidence_id) for item in events if item.evidence_id]
        if not evidence_ids:
            return "no_evidence"

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
            return "not_priced"

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
            return "withheld"

        point = history_point(goal, pricing)
        if point is not None:
            history = self._forecasts.history(goal_id)
            if any(item.material_hash == point.material_hash for item in history):
                return "unchanged"

        return await self._forecasts.publish(goal, pricing, critic)
