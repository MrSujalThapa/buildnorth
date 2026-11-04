from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from personal_markets.agents.critic import deterministic_critic_decision
from personal_markets.behavior.cohort import authentic_evidence, is_synthetic_goal
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.inputs_builder import build_numeric_inputs, proposal_from_goal
from personal_markets.forecasting.repository import history_point
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import (
    CriticArtifact,
    EvidenceEventProposal,
    GoalArchitectProposal,
    PricingResult,
)


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


def controlled_evidence_comparison(
    goal: GoalContract,
    proposal: GoalArchitectProposal,
    events: list[NormalizedEvidence],
    previous_evidence_ids: list[str] | None,
    current: PricingResult,
    forecasts: BaselineForecastService,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Isolate newly linked evidence while holding the clock and model fixed."""
    unavailable: dict[str, Any] = {
        "status": "unavailable",
        "delta_percentage_points": None,
        "interpretation": "Controlled model sensitivity, not a causal effect.",
    }
    if previous_evidence_ids is None:
        return {**unavailable, "reason": "No earlier published evidence set."}
    previous = set(previous_evidence_ids)
    current_ids = {str(item.evidence_id) for item in events if item.evidence_id}
    if not previous.issubset(current_ids):
        return {**unavailable, "reason": "The earlier evidence set cannot be replayed."}
    added = current_ids - previous
    if not added:
        return {**unavailable, "reason": "No newly linked evidence."}
    before_events = [item for item in events if str(item.evidence_id) in previous]
    before_numeric = build_numeric_inputs(goal, proposal, before_events, now=now)
    if before_numeric is None:
        return {**unavailable, "reason": "The earlier evidence set is not priceable."}
    before = forecasts.compute(
        goal,
        proposal,
        [str(item.evidence_id) for item in before_events if item.evidence_id],
        {},
        _research_ids(goal, proposal, before_numeric),
        before_numeric,
        evaluated_at=now,
    )
    if (
        not before.priced
        or before.raw_probability is None
        or not current.priced
        or current.raw_probability is None
        or before.model_version != current.model_version
    ):
        return {**unavailable, "reason": "Both states require the same priceable model."}
    current_numeric = build_numeric_inputs(goal, proposal, events, now=now)
    if before_numeric == current_numeric:
        return {
            **unavailable,
            "status": "informational",
            "reason": "New evidence did not change numerical model inputs.",
        }
    return {
        "status": "available",
        "before_probability": before.raw_probability,
        "after_probability": current.raw_probability,
        "delta_percentage_points": (current.raw_probability - before.raw_probability) * 100,
        "new_evidence_ids": sorted(added),
        "evaluated_at": now.isoformat(),
        "model_version": current.model_version,
        "interpretation": "Controlled model sensitivity, not a causal effect.",
    }


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
        if not is_synthetic_goal(goal):
            events = authentic_evidence(events)
        evidence_ids = [str(item.evidence_id) for item in events if item.evidence_id]
        if not evidence_ids:
            return RepriceResult(status="no_evidence", reason="No evidence is linked to this goal.")

        evaluation_time = datetime.now(UTC)
        numeric = build_numeric_inputs(goal, proposal, events, now=evaluation_time)
        pricing = self._forecasts.compute(
            goal,
            proposal,
            evidence_ids,
            {},
            _research_ids(goal, proposal, numeric),
            numeric,
            evaluated_at=evaluation_time,
        )
        history = await self._forecasts.published_history(goal_id)
        previous_raw = history[-1].receipt.get("normalized_evidence_ids") if history else None
        previous_ids = (
            [str(value) for value in previous_raw] if isinstance(previous_raw, list) else None
        )
        comparison = controlled_evidence_comparison(
            goal,
            proposal,
            events,
            previous_ids,
            pricing,
            self._forecasts,
            now=evaluation_time,
        )
        historical_change = (
            {
                "status": "available",
                "previous_published_probability": history[-1].probability,
                "candidate_probability": pricing.raw_probability,
                "delta_percentage_points": (
                    (pricing.raw_probability - history[-1].probability) * 100
                ),
                "interpretation": (
                    "Published-to-candidate change includes evidence, time, and model inputs."
                ),
            }
            if history and pricing.raw_probability is not None
            else {"status": "unavailable", "delta_percentage_points": None}
        )
        pricing = pricing.model_copy(
            update={
                "receipt": {
                    **pricing.receipt,
                    "controlled_evidence_comparison": comparison,
                    "historical_change": historical_change,
                }
            }
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
        if point is not None and any(item.material_hash == point.material_hash for item in history):
            matched = next(
                item for item in reversed(history) if item.material_hash == point.material_hash
            )
            return RepriceResult(
                status="unchanged",
                probability=matched.probability,
                receipt=dict(pricing.receipt),
            )

        status = await self._forecasts.publish(goal, pricing, critic)
        if status == "unchanged":
            # Publication deduplicates by evidence watermark. Return the immutable
            # receipt's odds, not a fresh clock-dependent candidate that was never
            # published and therefore does not appear in the chart.
            matching = (
                next(
                    (
                        item
                        for item in reversed(history)
                        if item.evidence_watermark == point.evidence_watermark
                    ),
                    None,
                )
                if point is not None
                else None
            )
            if matching is not None:
                return RepriceResult(
                    status="unchanged",
                    probability=matching.probability,
                    receipt=dict(matching.receipt),
                )
        if self._owner_id is not None:
            await self._goals.record_publication(goal_id, self._owner_id, critic, status)
        return RepriceResult(
            status=status,
            probability=pricing.raw_probability,
            receipt=dict(pricing.receipt),
        )
