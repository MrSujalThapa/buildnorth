import asyncio
from io import BytesIO
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError  # type: ignore[import-not-found]
from pydantic import BaseModel, Field

from personal_markets.behavior.cohort import behavior_cohort_goals
from personal_markets.behavior.commitments import get_commitment_store, trials_from_commitments
from personal_markets.behavior.domain import CommitmentTrial
from personal_markets.behavior.features import trials_from_evidence
from personal_markets.behavior.traits import (
    BUILT_IN_BY_ID,
    DEFAULT_TRAIT_IDS,
    CustomTraitDefinition,
    available_traits,
    custom_trait_from_name,
    estimate_traits,
)
from personal_markets.collections.service import CollectionService
from personal_markets.core.errors import ForbiddenError
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import (
    AccountView,
    CustomParameter,
    Principal,
    ProfileDimension,
    UserProfile,
)
from personal_markets.identity.factory import get_identity_service, get_inference_budget_service
from personal_markets.identity.service import IdentityService
from personal_markets.profile.photo_store import get_photo_store
from personal_markets.wiring import get_collection_service, get_evidence_service, get_goal_service

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])
MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_PIXELS = 8_000_000
MIN_RADAR_AXES = 3
MAX_RADAR_AXES = 10


class CustomParameterInput(BaseModel):
    name: str = Field(min_length=2, max_length=32)
    description: str = Field(min_length=4, max_length=160)


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    username: str | None = Field(default=None, max_length=24)
    bio: str | None = Field(default=None, max_length=280)
    avatar_value: str | None = Field(default=None, max_length=32)
    dimensions: list[ProfileDimension] | None = Field(default=None, max_length=12)
    parameter_ids: list[str] | None = Field(default=None, max_length=MAX_RADAR_AXES)
    custom_parameters: list[CustomParameterInput] | None = Field(default=None, max_length=6)


def _custom_definitions(profile: UserProfile) -> list[CustomTraitDefinition]:
    return [
        CustomTraitDefinition.model_validate(item.model_dump())
        for item in profile.custom_parameters
    ]


def selected_trait_ids(profile: UserProfile) -> list[str]:
    known = set(BUILT_IN_BY_ID) | {item.id for item in profile.custom_parameters}
    selected = [item for item in profile.parameter_ids if item in known]
    return selected if len(selected) >= MIN_RADAR_AXES else list(DEFAULT_TRAIT_IDS)


async def owner_trials_and_evidence(
    owner_id: UUID, goal_ids: list[UUID], evidence: EvidenceService
) -> tuple[list[CommitmentTrial], list[NormalizedEvidence]]:
    """All of an owner's planned-versus-observed trials plus goal evidence."""
    by_goal, (plans, observations) = await asyncio.gather(
        evidence.list_for_goals(goal_ids),
        get_commitment_store().list_for_goals(owner_id, goal_ids),
    )
    trials = trials_from_commitments(plans, observations)
    rows: list[NormalizedEvidence] = []
    for goal_id in goal_ids:
        items = by_goal.get(goal_id, [])
        rows.extend(items)
        trials.extend(
            trial.model_copy(update={"trial_id": f"{goal_id}:{trial.trial_id}"})
            for trial in trials_from_evidence(items)
        )
    return trials, rows


@router.get("")
async def get_profile(
    principal: Annotated[Principal, Depends(get_invited_principal)],
    identity: Annotated[IdentityService, Depends(get_identity_service)],
    budget: Annotated[InferenceBudgetService, Depends(get_inference_budget_service)],
    goals: Annotated[GoalService, Depends(get_goal_service)],
    collections: Annotated[CollectionService, Depends(get_collection_service)],
    evidence: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> dict[str, Any]:
    usage, profile, owned, collection_rows = await asyncio.gather(
        budget.usage_for(principal),
        identity.profile_for(principal),
        goals.list_goals(owner_id=principal.user_id),
        collections.list_for(principal.user_id),
    )
    account = await identity.account_view(principal, usage, profile)
    authentic_goals = behavior_cohort_goals(owned)
    trials, rows = await owner_trials_and_evidence(
        principal.user_id, [goal.goal_id for goal in authentic_goals], evidence
    )
    custom = _custom_definitions(account.profile)
    selected = selected_trait_ids(account.profile)
    traits = estimate_traits(trials, rows, selected=selected, custom=custom)
    return {
        "account": account.model_dump(mode="json"),
        "goal_count": len(owned),
        "collection_count": len(collection_rows),
        "traits": traits.model_dump(mode="json"),
        "selected_parameters": selected,
        "available_parameters": available_traits(custom),
        "privacy": "private",
    }


def _normalize_custom(items: list[CustomParameterInput]) -> list[CustomParameter]:
    normalized: list[CustomParameter] = []
    seen: set[str] = set()
    for item in items:
        definition = custom_trait_from_name(item.name, item.description)
        if definition.id in seen or definition.id.removeprefix("custom:") in BUILT_IN_BY_ID:
            raise HTTPException(status_code=422, detail=f"Duplicate parameter: {item.name}")
        seen.add(definition.id)
        normalized.append(CustomParameter.model_validate(definition.model_dump()))
    return normalized


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
    payload = body.model_dump(exclude_unset=True)
    if body.custom_parameters is not None:
        payload["custom_parameters"] = [
            item.model_dump() for item in _normalize_custom(body.custom_parameters)
        ]
    if body.parameter_ids is not None:
        if body.custom_parameters is not None:
            custom_ids = {item["id"] for item in payload["custom_parameters"]}
        else:
            current = await identity.account_view(principal, await budget.usage_for(principal))
            custom_ids = {item.id for item in current.profile.custom_parameters}
        known = set(BUILT_IN_BY_ID) | custom_ids
        unknown = [item for item in body.parameter_ids if item not in known]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown parameter ids: {', '.join(unknown)}",
            )
        if len(set(body.parameter_ids)) != len(body.parameter_ids):
            raise HTTPException(status_code=422, detail="Parameters must be unique")
        if len(body.parameter_ids) < MIN_RADAR_AXES:
            raise HTTPException(
                status_code=422,
                detail=f"Choose at least {MIN_RADAR_AXES} parameters for the radar",
            )
    await identity.update_profile(principal, UserProfile.model_validate(payload))
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
