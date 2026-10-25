"""Explicit owner-scoped persistence port for strategy learning."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from personal_markets.strategy_learning.domain import (
    Decision,
    OutcomeObservation,
    RecommendationTrial,
)


class StrategyLearningRepository(Protocol):
    async def create(self, trial: RecommendationTrial, fingerprint: str) -> RecommendationTrial: ...

    async def get(self, owner_id: UUID, trial_id: UUID) -> RecommendationTrial | None: ...

    async def decide(
        self, owner_id: UUID, trial_id: UUID, decision: Decision, at: datetime
    ) -> RecommendationTrial: ...

    async def observe(
        self, observation: OutcomeObservation, goal_id: UUID
    ) -> OutcomeObservation: ...

    async def history(
        self, owner_id: UUID, goal_id: UUID, as_of: datetime, *, include_synthetic: bool = False
    ) -> list[tuple[RecommendationTrial, OutcomeObservation | None]]: ...
