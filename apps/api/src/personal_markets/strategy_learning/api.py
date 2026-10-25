"""Authenticated polling, explicit generation, feedback, and outcome contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from personal_markets.core.config import get_settings
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.persistence.database import create_engine
from personal_markets.strategy_learning.context_source import PostgresGoalContextSource
from personal_markets.strategy_learning.domain import Decision, LearningContext, RecommendationTrial
from personal_markets.strategy_learning.postgres import PostgresStrategyLearningRepository
from personal_markets.strategy_learning.service import (
    GroundedFact,
    StrategyLearningService,
)
from personal_markets.wiring import build_inference, get_goal_service

router = APIRouter(
    prefix="/api/v1/goals/{goal_id}/strategy-recommendations", tags=["strategy-learning"]
)


def get_strategy_learning_service() -> StrategyLearningService:
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Strategy learning requires PostgreSQL")
    engine = create_engine(settings.database_url)
    return StrategyLearningService(
        PostgresStrategyLearningRepository(engine),
        get_goal_service(),
        build_inference(settings, None),
        PostgresGoalContextSource(engine),
    )


Service = Annotated[StrategyLearningService, Depends(get_strategy_learning_service)]
Owner = Annotated[Principal, Depends(get_invited_principal)]


class GenerateBody(BaseModel):
    user_constraints: list[str] = Field(default_factory=list, max_length=18)
    facts: list[GroundedFact] = Field(default_factory=list, max_length=10)
    milestone_key: str | None = None


class FeedbackBody(BaseModel):
    decision: Decision


class OutcomeBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    attempted: bool | None = None
    observed_value: float | None = None
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=30)
    observed_at: datetime
    observation_confidence: float = Field(ge=0, le=1)
    outcome_kind: str = Field(default="intermediate", pattern="^(intermediate|final)$")


@router.get("", response_model=LearningContext)
async def list_recommendations(goal_id: UUID, service: Service, owner: Owner) -> LearningContext:
    return await service.learning_context(owner.user_id, goal_id)


@router.post("", response_model=RecommendationTrial)
async def generate_recommendation(
    goal_id: UUID,
    body: GenerateBody,
    service: Service,
    owner: Owner,
) -> RecommendationTrial:
    if any(fact.kind in {"research", "relationship"} for fact in body.facts):
        raise HTTPException(status_code=422, detail="External facts require verified retrieval")
    try:
        return await service.recommend_from_goal(
            owner.user_id,
            goal_id,
            user_constraints=body.user_constraints,
            user_facts=[
                fact.model_copy(
                    update={"fact_id": f"user:{fact.fact_id}", "provenance": "user_entered"}
                )
                for fact in body.facts
            ],
            milestone_key=body.milestone_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.post("/{recommendation_id}/feedback", response_model=RecommendationTrial)
async def record_feedback(
    goal_id: UUID,
    recommendation_id: UUID,
    body: FeedbackBody,
    service: Service,
    owner: Owner,
) -> RecommendationTrial:
    trial = await service.get_recommendation(owner.user_id, goal_id, recommendation_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    try:
        return await service.feedback(owner.user_id, recommendation_id, body.decision)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.post("/{recommendation_id}/outcomes")
async def record_outcome(
    goal_id: UUID,
    recommendation_id: UUID,
    body: OutcomeBody,
    service: Service,
    owner: Owner,
) -> dict[str, object]:
    trial = await service.get_recommendation(owner.user_id, goal_id, recommendation_id)
    if trial is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    try:
        outcome = await service.record_outcome(
            owner.user_id,
            recommendation_id,
            idempotency_key=body.idempotency_key,
            attempted=body.attempted,
            observed_value=body.observed_value,
            evidence_ids=body.evidence_ids,
            observed_at=body.observed_at,
            observation_confidence=body.observation_confidence,
            outcome_kind=body.outcome_kind,
            provenance={"channel": "owner_feedback", "causal_claim": False},
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return outcome.model_dump(mode="json")
