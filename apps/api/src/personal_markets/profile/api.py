from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from personal_markets.behavior.portfolio import portfolio_profile
from personal_markets.collections.service import CollectionService
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import AccountView, Principal, UserProfile
from personal_markets.identity.factory import get_identity_service, get_inference_budget_service
from personal_markets.identity.service import IdentityService
from personal_markets.wiring import get_collection_service, get_evidence_service, get_goal_service

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    username: str | None = Field(default=None, max_length=24)
    bio: str | None = Field(default=None, max_length=280)
    avatar_value: str | None = Field(default=None, max_length=32)


@router.get("")
async def get_profile(
    principal: Annotated[Principal, Depends(get_invited_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    collections: Annotated[CollectionService, Depends(get_collection_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> dict[str, Any]:
    usage = await budget.usage_for(principal)
    account = await identity.account_view(principal, usage)
    owned = await goals.list_goals(owner_id=principal.user_id)
    grouped: dict[str, list] = {}
    for goal in owned:
        grouped[str(goal.goal_id)] = await evidence.list_for_goal(goal.goal_id)
    radar = portfolio_profile(owned, grouped)
    collection_rows = await collections.list_for(principal.user_id)
    return {
        "account": account.model_dump(mode="json"),
        "goal_count": len(owned),
        "collection_count": len(collection_rows),
        "radar": radar.model_dump(mode="json"),
        "privacy": "private",
    }


@router.patch("", response_model=AccountView)
async def patch_profile(
    body: ProfilePatch,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
) -> AccountView:
    await identity.update_profile(principal, UserProfile.model_validate(body.model_dump()))
    usage = await budget.usage_for(principal)
    return await identity.account_view(principal, usage)
