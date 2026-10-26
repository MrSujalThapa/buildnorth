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
    deadline: datetime | None = None
    success_criteria: dict[str, Any] = Field(default_factory=dict)
    milestones: list[Any] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    # "creator" is text the goal already stored. "suggested" is a template, not a commitment.
    strategies_source: Literal["creator", "suggested"] = "creator"
    milestones_source: Literal["creator", "suggested"] = "creator"
    evidence_types: list[str] = Field(default_factory=list)
    suggested_integrations: list[str] = Field(default_factory=list)
    model_configuration: dict[str, Any] = Field(default_factory=dict)
    forecast: PublicForecastState
    # Snapshots stored before versioning validate as schema version 1.
    blueprint_version: int = 1
    snapshot_at: datetime | None = None
    goal_contract_version: int | None = None
    tracked_metrics: list[str] = Field(default_factory=list)


class PublicModelChange(BaseModel):
    previous: str
    current: str


class PublicStatusChange(BaseModel):
    previous: str
    current: str


class PublicMarketUpdate(BaseModel):
    """One published forecast, described only with fields the receipt actually stored.

    Evidence is reported as counts plus metric names the owner published as tracked
    metrics; values, summaries and evidence identifiers never appear here.
    """

    published_at: datetime
    probability: float = Field(ge=0, le=1)
    previous_probability: float | None = Field(default=None, ge=0, le=1)
    change_points: float | None = None
    kind: Literal["first_publication", "update"]
    receipt_recorded: bool = False
    evidence_total: int | None = None
    new_evidence_count: int | None = None
    retired_evidence_count: int | None = None
    new_evidence_metrics: list[str] = Field(default_factory=list)
    other_new_evidence_count: int = 0
    model: str | None = None
    model_change: PublicModelChange | None = None
    status_change: PublicStatusChange | None = None
    definition_revised: bool = False
    deadline_changed: bool = False


class PublicModeledSensitivity(BaseModel):
    """Assumption names the latest published model used. Not a causal attribution."""

    published_at: datetime
    model: str | None = None
    drivers: list[str] = Field(default_factory=list)


class PublicCreator(BaseModel):
    user_id: UUID
    handle: str
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    has_photo: bool = False
    demo_persona: bool = False


class ForkProvenance(BaseModel):
    source_goal_id: UUID
    source_user_id: UUID
    source_handle: str | None = None
    source_title: str | None = None
    source_public: bool = False
    forked_at: datetime
    carried_fields: list[str] = Field(default_factory=list)


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
    updates: list[PublicMarketUpdate] = Field(default_factory=list)
    modeled_sensitivity: PublicModeledSensitivity | None = None


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
