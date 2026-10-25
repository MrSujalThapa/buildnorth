from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from personal_markets.identity.deps import get_invited_principal, get_optional_principal
from personal_markets.identity.domain import Principal
from personal_markets.profile.photo_store import get_photo_store
from personal_markets.social.domain import Visibility
from personal_markets.social.service import SocialService
from personal_markets.wiring import get_social_service

public_router = APIRouter(prefix="/api/v1/public", tags=["public"])
router = APIRouter(prefix="/api/v1/social", tags=["social"])


class VisibilityBody(BaseModel):
    visibility: Visibility


class ForkBody(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    deadline: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def _origin(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    scheme = forwarded or request.url.scheme
    if host:
        return f"{scheme}://{host}"
    return str(request.base_url).rstrip("/")


@public_router.get("/markets")
async def search_markets(
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
    q: str | None = None,
    category: str | None = None,
    sort: str = "newest",
    limit: int = Query(default=24, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
) -> dict[str, Any]:
    items = await service.search_markets(
        query=q,
        category=category,
        sort=sort,
        limit=limit,
        offset=offset,
        viewer_id=viewer.user_id if viewer else None,
    )
    return {"items": [item.model_dump(mode="json") for item in items]}


@public_router.get("/markets/{goal_id}")
async def get_public_market(
    goal_id: UUID,
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
) -> dict[str, Any]:
    detail = await service.public_market(goal_id, viewer.user_id if viewer else None)
    return detail.model_dump(mode="json")


@public_router.get("/blueprints/{goal_id}")
async def get_blueprint(
    goal_id: UUID,
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
) -> dict[str, Any]:
    detail = await service.public_market(goal_id, viewer.user_id if viewer else None)
    return {
        "goal_id": str(detail.goal_id),
        "blueprint": detail.blueprint.model_dump(mode="json"),
        "creator": detail.creator.model_dump(mode="json"),
        "share_path": detail.share_path,
    }


@public_router.get("/profiles/{handle}")
async def get_public_profile(
    handle: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
) -> dict[str, Any]:
    profile = await service.profile(handle, viewer.user_id if viewer else None)
    return profile.model_dump(mode="json")


@public_router.get("/profiles/{handle}/photo")
async def get_public_photo(
    handle: str, service: Annotated[SocialService, Depends(get_social_service)]
) -> Response:
    user_id = await service.resolve_handle(handle)
    content = await get_photo_store().get(user_id)
    if content is None:
        return Response(status_code=404)
    return Response(
        content, media_type="image/webp", headers={"Cache-Control": "public, max-age=120"}
    )


@public_router.get("/profiles/{handle}/markets")
async def get_profile_markets(
    handle: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
    q: str | None = None,
    visibility: Visibility | None = None,
    limit: int = Query(default=30, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
) -> dict[str, Any]:
    items = await service.profile_markets(
        handle,
        viewer.user_id if viewer else None,
        query=q,
        visibility=visibility,
        limit=limit,
        offset=offset,
    )
    return {"items": [item.model_dump(mode="json") for item in items]}


@public_router.get("/profiles/{handle}/stars")
async def get_profile_stars(
    handle: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    viewer: Annotated[Principal | None, Depends(get_optional_principal)],
    limit: int = Query(default=30, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
) -> dict[str, Any]:
    items = await service.profile_stars(handle, viewer.user_id if viewer else None, limit, offset)
    return {"items": [item.model_dump(mode="json") for item in items]}


@public_router.get("/profiles/{handle}/{kind}")
async def get_follow_graph(
    handle: str,
    kind: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    limit: int = Query(default=30, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
) -> dict[str, Any]:
    if kind not in {"followers", "following"}:
        return {"items": []}
    items = await service.follow_graph(handle, kind, limit, offset)
    return {"items": items}


@public_router.get("/creators")
async def discover_creators(
    service: Annotated[SocialService, Depends(get_social_service)],
    limit: int = Query(default=12, ge=1, le=30),
) -> dict[str, Any]:
    items = await service.discover_creators(limit)
    return {"items": [item.model_dump(mode="json") for item in items]}


@router.get("/markets/{goal_id}")
async def owner_market_social(
    goal_id: UUID,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return (await service.publish_preview(principal.user_id, goal_id)).model_dump(mode="json")


@router.post("/markets/{goal_id}/visibility")
async def set_visibility(
    goal_id: UUID,
    body: VisibilityBody,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return (await service.set_visibility(principal.user_id, goal_id, body.visibility)).model_dump(
        mode="json"
    )


@router.post("/markets/{goal_id}/star")
async def star_market(
    goal_id: UUID,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return await service.star(principal.user_id, goal_id)


@router.delete("/markets/{goal_id}/star")
async def unstar_market(
    goal_id: UUID,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return await service.unstar(principal.user_id, goal_id)


@router.post("/markets/{goal_id}/fork")
async def fork_market(
    goal_id: UUID,
    body: ForkBody,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return await service.fork(
        principal.user_id,
        goal_id,
        title=body.title,
        deadline=body.deadline,
        idempotency_key=body.idempotency_key,
    )


@router.get("/markets/{goal_id}/share")
async def share_market(
    goal_id: UUID,
    request: Request,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    preview = await service.publish_preview(principal.user_id, goal_id)
    if preview.visibility != "public":
        return {
            "shareable": False,
            "reason": "Publish this market before sharing a public link.",
        }
    return {
        "shareable": True,
        "url": service.share_url(goal_id, _origin(request)),
        "title": preview.public_preview.title if preview.public_preview else "PlayItOut market",
    }


@router.post("/profiles/{handle}/follow")
async def follow_profile(
    handle: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return await service.follow(principal.user_id, handle)


@router.delete("/profiles/{handle}/follow")
async def unfollow_profile(
    handle: str,
    service: Annotated[SocialService, Depends(get_social_service)],
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> dict[str, Any]:
    return await service.unfollow(principal.user_id, handle)
