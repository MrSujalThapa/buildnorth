from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CollectionRecord(BaseModel):
    collection_id: UUID
    owner_id: UUID
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    icon: str | None = None
    color: str | None = None
    position: int = 0
    goal_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CollectionProgress(BaseModel):
    label: str = "progress"
    value: float | None = None
    available: int = 0
    total: int = 0
    incomplete: bool = True
    methodology: str
    notes: list[str] = Field(default_factory=list)


class CollectionSeries(BaseModel):
    goal_id: UUID
    title: str
    color: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    withheld: bool = False


class CollectionView(BaseModel):
    collection: CollectionRecord
    progress: CollectionProgress
    series: list[CollectionSeries] = Field(default_factory=list)
    portfolio_odds: float | None = None
    change_pp: float | None = None
    priced_goals: int = 0
    total_goals: int = 0
    portfolio_methodology: str = (
        "Equal-weight average of currently published member-goal probabilities. "
        "This is a portfolio summary, not the probability that every goal succeeds."
    )
