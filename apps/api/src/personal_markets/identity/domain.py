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
    kill_switch: bool = False
    billing_note: str = Field(
        default=(
            "These counters are application-enforced estimates. They do not guarantee "
            "a hard upstream provider billing ceiling."
        )
    )


class AccountView(BaseModel):
    user_id: UUID
    clerk_user_id: str
    email: str | None
    email_verified: bool
    role: Role
    invited: bool
    hosted: HostedUsage
