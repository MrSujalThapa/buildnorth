from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, Field

from personal_markets.agents.state import NAMESPACE

Role = Literal["user", "admin"]
InviteKind = Literal["email", "shared"]


def user_id_for_clerk(clerk_user_id: str) -> UUID:
    return uuid5(NAMESPACE, f"playitout:clerk:{clerk_user_id}")


class Principal(BaseModel):
    user_id: UUID
    clerk_user_id: str
    email: str | None = None
    email_verified: bool = False
    role: Role = "user"
    invited: bool = False
    hosted_enabled: bool = False
    hosted_quota_usd: float = 0.0
    hosted_quota_tokens: int = 0


class InvitationHistory(BaseModel):
    invitation_id: UUID
    email: str | None = None
    note: str = ""
    kind: InviteKind = "email"
    max_redemptions: int = 1
    redemption_count: int = 0
    hosted_quota_usd: float
    hosted_quota_tokens: int
    expires_at: datetime
    created_by: UUID | None = None
    revoked_at: datetime | None = None
    redeemed_at: datetime | None = None
    redeemed_by: UUID | None = None


class Invitation(InvitationHistory):
    token: str | None = None

    def to_history(self) -> InvitationHistory:
        return InvitationHistory.model_validate(self.model_dump(exclude={"token"}))


class RedeemResult(BaseModel):
    invitation: Invitation
    already_redeemed: bool = False


class HostedUsage(BaseModel):
    enabled: bool
    quota_usd: float
    quota_tokens: int
    reserved_usd: float = 0.0
    spent_usd: float = 0.0
    reserved_tokens: int = 0
    spent_tokens: int = 0
    remaining_usd: float = 0.0
    remaining_tokens: int = 0
    global_remaining_usd: float | None = None
    hosted_available: bool = False
    kill_switch: bool = False
    billing_note: str = Field(
        default=(
            "These counters are application-enforced estimates. They do not guarantee "
            "a hard upstream provider billing ceiling."
        )
    )


class ProfileDimension(BaseModel):
    label: str = Field(min_length=1, max_length=32)
    goal_ids: list[UUID] = Field(default_factory=list)


PARAMETER_MARKER_PREFIX = "__param__:"


class CustomParameter(BaseModel):
    """User-defined radar trait. Scored only from evidence recorded on `metric`."""

    id: str = Field(min_length=8, max_length=48)
    name: str = Field(min_length=2, max_length=32)
    description: str = Field(min_length=4, max_length=160)
    metric: str = Field(min_length=7, max_length=48)
    scale_min: float = 0.0
    scale_max: float = 1.0


class UserProfile(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    username: str | None = None
    bio: str | None = Field(default=None, max_length=280)
    avatar_value: str | None = Field(default=None, max_length=32)
    dimensions: list[ProfileDimension] = Field(default_factory=list, max_length=12)
    parameter_ids: list[str] = Field(default_factory=list, max_length=10)
    custom_parameters: list[CustomParameter] = Field(default_factory=list, max_length=6)


def split_stored_parameters(
    raw: object,
) -> tuple[list[str], list[CustomParameter]] | None:
    """Read `profile_parameters_json`. None means the row predates the column."""
    if not isinstance(raw, dict) or "selected" not in raw:
        return None
    selected = [str(item) for item in raw.get("selected") or [] if item]
    custom: list[CustomParameter] = []
    for item in raw.get("custom") or []:
        try:
            custom.append(CustomParameter.model_validate(item))
        except ValueError:
            continue
    return selected, custom


def split_stored_dimensions(
    raw: object,
) -> tuple[list[ProfileDimension], list[str]]:
    items = raw or []
    areas: list[ProfileDimension] = []
    parameter_ids: list[str] = []
    if not isinstance(items, list):
        return areas, parameter_ids
    for item in items:
        data = item if isinstance(item, dict) else None
        if data is None and hasattr(item, "model_dump"):
            data = item.model_dump(mode="json")
        if not isinstance(data, dict):
            continue
        label = str(data.get("label") or "")
        if label.startswith(PARAMETER_MARKER_PREFIX):
            marker = label[len(PARAMETER_MARKER_PREFIX) :]
            if marker:
                parameter_ids.append(marker)
            continue
        areas.append(ProfileDimension.model_validate(data))
    return areas, parameter_ids


def merge_stored_dimensions(
    areas: list[ProfileDimension],
    parameter_ids: list[str],
) -> list[dict[str, object]]:
    markers = [
        {"label": f"{PARAMETER_MARKER_PREFIX}{item}", "goal_ids": []}
        for item in parameter_ids
        if item
    ]
    return [item.model_dump(mode="json") for item in areas] + markers


class AccountView(BaseModel):
    user_id: UUID
    clerk_user_id: str
    email: str | None
    email_verified: bool
    role: Role
    invited: bool
    hosted: HostedUsage
    profile: UserProfile = Field(default_factory=UserProfile)
