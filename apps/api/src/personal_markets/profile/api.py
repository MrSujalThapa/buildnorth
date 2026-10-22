import asyncio
from io import BytesIO
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError  # type: ignore[import-not-found]
from pydantic import BaseModel, Field

from personal_markets.behavior.commitments import get_commitment_store, trials_from_commitments
from personal_markets.behavior.portfolio import portfolio_profile
from personal_markets.collections.service import CollectionService
from personal_markets.core.errors import ForbiddenError
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import AccountView, Principal, ProfileDimension, UserProfile
from personal_markets.identity.factory import get_identity_service, get_inference_budget_service
from personal_markets.identity.service import IdentityService
from personal_markets.profile.photo_store import get_photo_store
from personal_markets.wiring import get_collection_service, get_evidence_service, get_goal_service

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_PIXELS = 8_000_000


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    username: str | None = Field(default=None, max_length=24)
    bio: str | None = Field(default=None, max_length=280)
    avatar_value: str | None = Field(default=None, max_length=32)
    dimensions: list[ProfileDimension] | None = Field(default=None, max_length=12)


@router.get("")
async def get_profile(
    principal: Annotated[Principal, Depends(get_invited_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    collections: Annotated[CollectionService, Depends(get_collection_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> dict[str, Any]:
    usage, owned, collection_rows = await asyncio.gather(
        budget.usage_for(principal),
        goals.list_goals(owner_id=principal.user_id),
        collections.list_for(principal.user_id),
    )
    account = await identity.account_view(principal, usage)
    evidence_limit = asyncio.Semaphore(8)

    async def goal_evidence(goal_id: UUID) -> list[NormalizedEvidence]:
        async with evidence_limit:
            return await evidence.list_for_goal(goal_id)

    event_rows = await asyncio.gather(*(goal_evidence(goal.goal_id) for goal in owned))
    grouped = {str(goal.goal_id): rows for goal, rows in zip(owned, event_rows, strict=True)}
    commitments, observations = await get_commitment_store().list_for_goals(
        principal.user_id, [goal.goal_id for goal in owned]
    )
    explicit_trials = trials_from_commitments(commitments, observations)
    plan_goals = {str(plan.id): plan.goal_id for plan in commitments}
    radar = portfolio_profile(
        owned,
        grouped,
        dimensions=account.profile.dimensions,
        commitment_trials=explicit_trials,
    )
    radar_areas = []
    for area in account.profile.dimensions:
        members = [goal for goal in owned if goal.goal_id in area.goal_ids]
        if members:
            radar_areas.append(
                {
                    "label": area.label,
                    "radar": portfolio_profile(
                        members,
                        grouped,
                        commitment_trials=[
                            trial
                            for trial in explicit_trials
                            if plan_goals.get(trial.trial_id.split(":")[1]) in area.goal_ids
                        ],
                    ).model_dump(mode="json"),
                }
            )
    return {
        "account": account.model_dump(mode="json"),
        "goal_count": len(owned),
        "collection_count": len(collection_rows),
        "radar": radar.model_dump(mode="json"),
        "radar_areas": radar_areas,
        "privacy": "private",
    }


@router.patch("", response_model=AccountView)
async def patch_profile(
    body: ProfilePatch,
    principal: Annotated[Principal, Depends(get_invited_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
) -> AccountView:
    if body.dimensions is not None:
        owned = {goal.goal_id for goal in await goals.list_goals(owner_id=principal.user_id)}
        if any(goal_id not in owned for item in body.dimensions for goal_id in item.goal_ids):
            raise ForbiddenError("Profile dimensions may include only your goals")
    await identity.update_profile(
        principal, UserProfile.model_validate(body.model_dump(exclude_unset=True))
    )
    usage = await budget.usage_for(principal)
    return await identity.account_view(principal, usage)


@router.get("/photo")
async def get_photo(
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> Response:
    content = await get_photo_store().get(principal.user_id)
    if content is None:
        raise HTTPException(status_code=404, detail="No profile photo")
    return Response(
        content, media_type="image/webp", headers={"Cache-Control": "private, no-store"}
    )


@router.put("/photo")
async def put_photo(
    principal: Annotated[Principal, Depends(get_invited_principal)],
    file: Annotated[UploadFile, File()],
) -> dict[str, str]:
    raw = await file.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo must be under 2 MB")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format")
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise ValueError("Image dimensions are too large")
            converted = ImageOps.exif_transpose(image).convert("RGB")
            converted.thumbnail((512, 512))
            output = BytesIO()
            converted.save(output, format="WEBP", quality=84)
    except (UnidentifiedImageError, ValueError, OSError) as error:
        raise HTTPException(
            status_code=422, detail="Choose a valid JPEG, PNG or WebP photo"
        ) from error
    await get_photo_store().put(principal.user_id, output.getvalue())
    return {"status": "saved"}


@router.delete("/photo")
async def delete_photo(
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, str]:
    await get_photo_store().delete(principal.user_id)
    return {"status": "removed"}
