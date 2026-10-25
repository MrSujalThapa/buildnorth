from typing import Any
from uuid import UUID

from fastapi import FastAPI

from personal_markets.core.config import Settings
from personal_markets.identity.domain import Principal
from personal_markets.remote_mcp.server import RemoteMcp, build_remote_mcp
from personal_markets.remote_mcp.store import (
    InMemoryRemoteMcpStore,
    PostgresRemoteMcpStore,
    RemoteMcpStore,
)
from personal_markets.remote_mcp.tools import RemoteMcpTools


def build_store(settings: Settings) -> RemoteMcpStore:
    if not settings.database_url or settings.environment in {"test", "pytest"}:
        return InMemoryRemoteMcpStore()
    from personal_markets.identity.credentials import CredentialCipher
    from personal_markets.persistence.database import create_engine

    cipher = (
        CredentialCipher(settings.byok_encryption_keys, settings.byok_active_key_id)
        if settings.byok_encryption_keys
        else None
    )
    return PostgresRemoteMcpStore(create_engine(settings.database_url), cipher)


async def _lookup_user(user_id: UUID) -> Principal | None:
    from personal_markets.identity.factory import get_identity_service

    principal: Principal | None = await get_identity_service().principal_for_user_id(user_id)
    return principal


def mount_remote_mcp(application: FastAPI, settings: Settings) -> RemoteMcp:
    """Attach /mcp and its OAuth endpoints. Services resolve lazily from app state."""

    def deps() -> Any:
        return application.state.agent_workflow._inner._deps

    def workflow() -> Any:
        return application.state.agent_workflow

    def uploads() -> Any:
        return getattr(application.state, "upload_service", None)

    def what_if(principal: Principal) -> Any:
        override = getattr(application.state, "remote_mcp_what_if", None)
        if override is not None:
            return override(principal)
        from personal_markets.what_if.service import WhatIfService
        from personal_markets.wiring import get_simulation_repository

        current = deps()
        return WhatIfService(
            current.goals,
            get_simulation_repository(),
            evidence=current.evidence,
            owner_id=principal.user_id,
            forecasts=current.baseline_forecasts,
        )

    store = build_store(settings)
    tools = RemoteMcpTools(
        settings=settings,
        store=store,
        deps=deps,
        what_if=what_if,
        workflow=workflow,
        uploads=uploads,
    )
    remote = build_remote_mcp(settings=settings, store=store, users=_lookup_user, tools=tools)
    application.router.routes.extend(remote.routes)
    application.state.remote_mcp = remote
    return remote
