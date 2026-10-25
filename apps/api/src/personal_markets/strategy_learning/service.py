"""Personal strategy learning without causal or probability claims."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from personal_markets.agents.completion import complete_validated
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.ports import InferenceProvider, InferenceRequest
from personal_markets.strategy_learning.domain import (
    BlueprintCandidate,
    Decision,
    LearningContext,
    OutcomeObservation,
    OutcomeStatus,
    RecommendationDraft,
    RecommendationTrial,
)
from personal_markets.strategy_learning.repository import StrategyLearningRepository

PROMPT_VERSION = "strategy_learning_v1"
INSTRUCTIONS = """Recommend one concrete, measurable next action for the user's goal.
Use only the supplied facts, constraints, progress and previous strategy outcomes.
The prior outcomes are observations, never proof that a strategy caused progress.
Do not invent personal relationships, citations, or odds; leave numerical effects unpriced.
Use a general, extensible snake_case strategy_key. Return only the requested JSON schema.
Every factual reference must appear in grounded_fact_ids, external_citations or
claimed_relationship_ids, using IDs present in the input. Explicitly state assumptions.
Prefer a different approach when a prior attempted strategy had poor measured results.
"""
_PROBABILITY_CLAIM = re.compile(
    r"\b(?:odds|probability|chance)\s+(?:of|by|is|rise|fall)?\s*\d|\b\d+(?:\.\d+)?\s*%",
    re.I,
)


class GroundedFact(BaseModel):
    fact_id: str = Field(min_length=1, max_length=100)
    statement: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    available_at: datetime | None = None
    provenance: str = Field(min_length=1, max_length=300)
    kind: str = Field(pattern="^(progress|evidence|constraint|relationship|research)$")


class RecommendationContext(BaseModel):
    facts: list[GroundedFact] = Field(default_factory=list, max_length=30)
    progress: dict[str, Any] = Field(default_factory=dict)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=20)
    user_constraints: list[str] = Field(default_factory=list, max_length=20)
    external_research: list[GroundedFact] = Field(default_factory=list, max_length=10)
    as_of: datetime


class ReviewedBlueprintSource(Protocol):
    """Optional future marketplace port; no implementation or dependency in Pass 9B."""

    async def candidates(self, goal_family: str) -> list[BlueprintCandidate]: ...


class GoalContextSource(Protocol):
    async def build(
        self, owner_id: UUID, goal: GoalContract, as_of: datetime
    ) -> RecommendationContext: ...


def _validate_draft(draft: RecommendationDraft, context: RecommendationContext) -> None:
    facts = {fact.fact_id: fact for fact in [*context.facts, *context.external_research]}
    if len(facts) != len(context.facts) + len(context.external_research):
        raise ValueError("Grounded fact IDs must be unique")
    if any(
        fact.observed_at > context.as_of
        or (fact.available_at is not None and fact.available_at > context.as_of)
        for fact in facts.values()
    ):
        raise ValueError("Future context cannot inform a current recommendation")
    if not set(draft.grounded_fact_ids).issubset(facts):
        raise ValueError("Recommendation references an ungrounded fact")
    research = {key for key, value in facts.items() if value.kind == "research"}
    relationships = {key for key, value in facts.items() if value.kind == "relationship"}
    if not set(draft.external_citations).issubset(research):
        raise ValueError("Recommendation cites unverified external research")
    if not set(draft.claimed_relationship_ids).issubset(relationships):
        raise ValueError("Recommendation claims an unknown relationship")
    if draft.expected.horizon <= context.as_of:
        raise ValueError("Evaluation horizon must follow the recommendation")
    prose = " ".join((draft.action, draft.why_now, draft.next_step, *draft.assumptions))
    if _PROBABILITY_CLAIM.search(prose):
        raise ValueError("Recommendations cannot invent numerical probability effects")


class StrategyLearningService:
    def __init__(
        self,
        repository: StrategyLearningRepository,
        goals: GoalService,
        inference: InferenceProvider | None = None,
        context_source: GoalContextSource | None = None,
    ) -> None:
        self._repository = repository
        self._goals = goals
        self._inference = inference
        self._context_source = context_source

    async def recommend_from_goal(
        self,
        owner_id: UUID,
        goal_id: UUID,
        *,
        user_constraints: list[str] | None = None,
        user_facts: list[GroundedFact] | None = None,
        milestone_key: str | None = None,
    ) -> RecommendationTrial:
        if self._context_source is None:
            raise RuntimeError("A trusted goal context source is required")
        goal = await self._goals.get_goal(goal_id, owner_id)
        context = await self._context_source.build(owner_id, goal, datetime.now(UTC))
        context = RecommendationContext.model_validate(
            {
                **context.model_dump(),
                "user_constraints": [*context.user_constraints, *(user_constraints or [])],
                "facts": [*context.facts, *(user_facts or [])],
            }
        )
        return await self.recommend(owner_id, goal_id, context, milestone_key=milestone_key)

    async def learning_context(
        self,
        owner_id: UUID,
        goal_id: UUID,
        *,
        as_of: datetime | None = None,
        include_synthetic: bool = False,
    ) -> LearningContext:
        await self._goals.get_goal(goal_id, owner_id)
        stamp = as_of or datetime.now(UTC)
        history = await self._repository.history(
            owner_id, goal_id, stamp, include_synthetic=include_synthetic
        )
        records = []
        for trial, outcome in history:
            records.append(
                {
                    "recommendation_id": str(trial.recommendation_id),
                    "strategy_key": trial.strategy_key,
                    "action": trial.action,
                    "recommended_at": trial.proposed_at.isoformat(),
                    "decision": (
                        trial.decision
                        if trial.decided_at is None or trial.decided_at <= stamp
                        else Decision.PENDING
                    ),
                    "expected": trial.expected.model_dump(mode="json"),
                    "attempted": outcome.attempted if outcome else None,
                    "observed_value": outcome.observed_value if outcome else None,
                    "outcome_status": outcome.status if outcome else "not_observed",
                    "observed_at": outcome.observed_at.isoformat() if outcome else None,
                    "evidence_ids": [str(key) for key in outcome.evidence_ids] if outcome else [],
                    "observation_confidence": outcome.observation_confidence if outcome else None,
                    "provenance": outcome.provenance if outcome else None,
                }
            )
        return LearningContext(goal_id=goal_id, as_of=stamp, past_trials=records)

    async def get_recommendation(
        self, owner_id: UUID, goal_id: UUID, recommendation_id: UUID
    ) -> RecommendationTrial | None:
        trial = await self._repository.get(owner_id, recommendation_id)
        return trial if trial is not None and trial.goal_id == goal_id else None

    async def recommend(
        self,
        owner_id: UUID,
        goal_id: UUID,
        context: RecommendationContext,
        *,
        milestone_key: str | None = None,
        include_synthetic: bool = False,
    ) -> RecommendationTrial:
        if self._inference is None:
            raise RuntimeError("A configured inference provider is required")
        goal = await self._goals.get_goal(goal_id, owner_id)
        candidates = await self._repository.history(
            owner_id, goal_id, context.as_of, include_synthetic=include_synthetic
        )
        for existing, observed in candidates:
            if (
                existing.decision == Decision.PENDING
                and observed is None
                and existing.milestone_key == milestone_key
                and existing.context.get("progress") == context.progress
                and existing.context.get("evidence_gaps") == context.evidence_gaps
                and existing.context.get("user_constraints") == context.user_constraints
                and existing.context.get("facts")
                == [fact.model_dump(mode="json") for fact in context.facts]
            ):
                return existing
        past = await self.learning_context(
            owner_id, goal_id, as_of=context.as_of, include_synthetic=include_synthetic
        )
        input_payload = {
            "goal": goal.model_dump(mode="json"),
            "deadline": goal.deadline.isoformat(),
            "current_progress": context.progress,
            "evidence_gaps": context.evidence_gaps,
            "user_constraints": context.user_constraints,
            "grounded_facts": [fact.model_dump(mode="json") for fact in context.facts],
            "external_research": [
                fact.model_dump(mode="json") for fact in context.external_research
            ],
            "previous_strategy_outcomes": past.model_dump(mode="json"),
            "as_of": context.as_of.isoformat(),
        }
        request = InferenceRequest(
            instructions=INSTRUCTIONS,
            input=input_payload,
            output_schema=RecommendationDraft.model_json_schema(),
            agent_name="strategy_learning",
            user_id=owner_id,
            max_output_tokens=900,
        )
        draft, response = await complete_validated(
            self._inference, request, RecommendationDraft, timeout_seconds=90
        )
        _validate_draft(draft, context)
        context_snapshot = context.model_dump(mode="json")
        context_snapshot["grounded_fact_ids"] = draft.grounded_fact_ids
        context_snapshot["external_citations"] = draft.external_citations
        context_snapshot["claimed_relationship_ids"] = draft.claimed_relationship_ids
        context_snapshot["previous_strategy_outcomes"] = past.model_dump(mode="json")
        trial = RecommendationTrial(
            **draft.model_dump(),
            recommendation_id=uuid4(),
            owner_id=owner_id,
            goal_id=goal_id,
            milestone_key=milestone_key,
            context=context_snapshot,
            provenance={
                "agent": "strategy_learning",
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
                "provider": response.provider,
                "model": response.model,
                "request_id": response.request_id,
            },
            proposed_at=context.as_of,
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "owner": str(owner_id),
                    "goal": str(goal_id),
                    "strategy": draft.strategy_key,
                    "action": draft.action.strip().casefold(),
                    "horizon": draft.expected.horizon.isoformat(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return await self._repository.create(trial, fingerprint)

    async def feedback(
        self,
        owner_id: UUID,
        trial_id: UUID,
        decision: Decision,
        *,
        at: datetime | None = None,
    ) -> RecommendationTrial:
        return await self._repository.decide(owner_id, trial_id, decision, at or datetime.now(UTC))

    async def record_outcome(
        self,
        owner_id: UUID,
        trial_id: UUID,
        *,
        idempotency_key: str,
        attempted: bool | None,
        observed_value: float | None,
        evidence_ids: list[UUID],
        observed_at: datetime,
        provenance: dict[str, Any],
        observation_confidence: float,
        outcome_kind: str = "intermediate",
    ) -> OutcomeObservation:
        trial = await self._repository.get(owner_id, trial_id)
        if trial is None:
            raise ValueError("Recommendation is unavailable for this owner")
        if observed_at < trial.proposed_at:
            raise ValueError("Outcome predates recommendation")
        target = trial.expected.target
        status = OutcomeStatus.INSUFFICIENT_EVIDENCE
        if attempted is True and observed_value is not None and evidence_ids and target is not None:
            direction = trial.expected.direction
            passed = (
                observed_value >= target
                if direction == "increase"
                else observed_value <= target
                if direction == "decrease"
                else observed_value == target
            )
            status = (
                OutcomeStatus.SUCCESSFUL
                if passed
                else OutcomeStatus.UNSUCCESSFUL
                if observed_at >= trial.expected.horizon
                else OutcomeStatus.PENDING
            )
        elif observed_at < trial.expected.horizon:
            status = OutcomeStatus.PENDING
        elif attempted is True and observed_value is not None:
            status = OutcomeStatus.INCONCLUSIVE
        observation = OutcomeObservation(
            observation_id=uuid4(),
            recommendation_id=trial_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            attempted=attempted,
            observed_value=observed_value,
            status=status,
            observation_confidence=observation_confidence,
            provenance=provenance,
            observed_at=observed_at,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            outcome_kind=outcome_kind,
        )
        return await self._repository.observe(observation, trial.goal_id)
