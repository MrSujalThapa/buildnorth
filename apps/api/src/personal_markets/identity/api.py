import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.deps import get_admin_principal, get_principal
from personal_markets.identity.domain import (
    AccountView,
    Invitation,
    InvitationHistory,
    Principal,
)
from personal_markets.identity.factory import get_identity_service, get_inference_budget_service
from personal_markets.identity.service import IdentityService

router = APIRouter(prefix="/api/v1", tags=["identity"])


class CreateInviteBody(BaseModel):
    email: str | None = None
    note: str = ""
    hosted_quota_usd: float | None = None
    hosted_quota_tokens: int | None = None
    ttl_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    max_redemptions: int | None = Field(default=None, ge=1, le=20)


class RedeemInviteBody(BaseModel):
    token: str = Field(min_length=8)


class KillSwitchBody(BaseModel):
    enabled: bool


@router.get("/me", response_model=AccountView)
async def me(
    principal: Annotated[Principal, Depends(get_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
) -> AccountView:
    usage, profile = await asyncio.gather(
        budget.usage_for(principal), identity.profile_for(principal)
    )
    return await identity.account_view(principal, usage, profile)


@router.post("/invites/redeem", response_model=AccountView)
async def redeem_invite(
    body: RedeemInviteBody,
    principal: Annotated[Principal, Depends(get_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
) -> AccountView:
    updated = await identity.redeem_invitation(principal, body.token)
    usage = await budget.usage_for(updated)
    return await identity.account_view(updated, usage)


@router.post("/admin/invites", response_model=Invitation)
async def create_invite(
    body: CreateInviteBody,
    principal: Annotated[Principal, Depends(get_admin_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
) -> Invitation:
    return await identity.create_invitation(
        principal,
        email=body.email,
        note=body.note,
        hosted_quota_usd=body.hosted_quota_usd,
        hosted_quota_tokens=body.hosted_quota_tokens,
        ttl_hours=body.ttl_hours,
        max_redemptions=body.max_redemptions,
    )


@router.get("/admin/invites", response_model=list[InvitationHistory])
async def list_invites(
    principal: Annotated[Principal, Depends(get_admin_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[InvitationHistory]:
    return [item.to_history() for item in await identity.list_invitations(principal)]


@router.post("/admin/invites/{invitation_id}/revoke", response_model=InvitationHistory)
async def revoke_invite(
    invitation_id: UUID,
    principal: Annotated[Principal, Depends(get_admin_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
) -> InvitationHistory:
    return (await identity.revoke_invitation(principal, invitation_id)).to_history()


@router.post("/admin/hosted-inference")
async def set_hosted_kill_switch(
    body: KillSwitchBody,
    principal: Annotated[Principal, Depends(get_admin_principal)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
) -> dict[str, bool]:
    del principal
    await budget.set_kill_switch(body.enabled)
    return {"hosted_inference_enabled": body.enabled}
