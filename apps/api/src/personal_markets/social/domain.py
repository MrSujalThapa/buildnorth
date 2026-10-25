from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Visibility = Literal["private", "public"]
ActivityType = Literal["market_created", "market_published", "evidence_accepted"]
MarketSort = Literal["newest", "updated", "stars", "forks"]


class PublicForecastState(BaseModel):
    status: Literal["published", "withheld", "unpublished", "exploratory"]
    category: str | None = None


class PublicHistoryPoint(BaseModel):
    created_at: datetime
    probability: float = Field(ge=0, le=1)


class PublicBlueprint(BaseModel):
    title: str
    description: str = ""
    category: str
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    milestones: list[Any] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    suggested_integrations: list[str] = Field(default_factory=list)
    model_configuration: dict[str, Any] = Field(default_factory=dict)
    forecast: PublicForecastState


class PublicCreator(BaseModel):
    user_id: UUID
    handle: str
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    has_photo: bool = False


class ForkProvenance(BaseModel):
    source_goal_id: UUID
    source_user_id: UUID
    source_handle: str | None = None
    source_title: str | None = None
    source_public: bool = False
    forked_at: datetime


class PublicMarketCard(BaseModel):
    goal_id: UUID
    title: str
    description: str = ""
    category: str
    visibility: Visibility = "public"
    creator: PublicCreator
    star_count: int = 0
    fork_count: int = 0
    starred: bool = False
    published_at: datetime | None = None
    updated_at: datetime | None = None
    latest_probability: float | None = Field(default=None, ge=0, le=1)
    forecast: PublicForecastState
    history: list[PublicHistoryPoint] = Field(default_factory=list)
    fork: ForkProvenance | None = None


class PublicMarketDetail(PublicMarketCard):
    blueprint: PublicBlueprint
    share_path: str


class OwnerMarketSocial(BaseModel):
    goal_id: UUID
    visibility: Visibility
    published_at: datetime | None = None
    star_count: int = 0
    fork_count: int = 0
    starred: bool = False
    public_preview: PublicBlueprint | None = None
    fork: ForkProvenance | None = None


class ActivityDay(BaseModel):
    day: date
    count: int = 0


class PublicProfile(BaseModel):
    creator: PublicCreator
    follower_count: int = 0
    following_count: int = 0
    following: bool = False
    is_self: bool = False
    market_count: int = 0
    contribution_total: int = 0
    activity: list[ActivityDay] = Field(default_factory=list)


class FollowRecord(BaseModel):
    creator: PublicCreator
    created_at: datetime
