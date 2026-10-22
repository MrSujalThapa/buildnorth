from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from personal_markets.behavior.commitments import get_commitment_store
from personal_markets.collections.service import CollectionService
from personal_markets.core.config import get_settings
from personal_markets.identity.deps import get_admin_principal
from personal_markets.identity.domain import Principal
from personal_markets.persistence.database import create_engine
from personal_markets.wiring import _use_postgres, _workflow_deps, get_collection_repository
from personal_markets.workspace_seed.registry import InMemorySeedRegistry, PostgresSeedRegistry
from personal_markets.workspace_seed.service import SeedRegistry, WorkspaceSeedService

router = APIRouter(prefix="/api/v1/admin/workspace-seed", tags=["admin"])


@lru_cache
def get_seed_registry() -> SeedRegistry:
    if not _use_postgres():
        return InMemorySeedRegistry()
    return PostgresSeedRegistry(create_engine(get_settings().database_url or ""))


def get_workspace_seed_service(request: Request) -> WorkspaceSeedService:
    deps = _workflow_deps(request)
    return WorkspaceSeedService(
        goals=deps.goals,
        evidence=deps.evidence,
        forecasts=deps.baseline_forecasts,
        collections=CollectionService(get_collection_repository(), deps.goals),
        commitments=get_commitment_store(),
        registry=get_seed_registry(),
    )


Admin = Annotated[Principal, Depends(get_admin_principal)]
Service = Annotated[WorkspaceSeedService, Depends(get_workspace_seed_service)]


@router.get("")
async def seed_status(principal: Admin, service: Service) -> dict[str, Any]:
    return await service.status(principal.user_id)


@router.post("")
async def seed_workspace(principal: Admin, service: Service) -> dict[str, Any]:
    return await service.seed(principal.user_id)


@router.delete("")
async def remove_seed(principal: Admin, service: Service) -> dict[str, int]:
    return await service.remove(principal.user_id)
